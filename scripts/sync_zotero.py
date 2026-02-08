#!/usr/bin/env python3
"""Fetch publications from Zotero 'My Publications' and generate publications.qmd."""

import json
import os
import re
import sys
import urllib.request
import urllib.error

ZOTERO_USER_ID = os.environ.get("ZOTERO_USER_ID", "")
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "publications.qmd")

FRONT_MATTER = """\
---
title: "Publications"
---

Full publication list available on [Google Scholar](https://scholar.google.ca/citations?user=iWPPB7AAAAAJ&hl) and [PubMed](https://pubmed.ncbi.nlm.nih.gov/?term=richer+l&sort=date).

---
"""


def fetch_items():
    """Fetch all journal articles from Zotero My Publications, handling pagination."""
    if not ZOTERO_USER_ID:
        print("Error: ZOTERO_USER_ID environment variable is required.", file=sys.stderr)
        sys.exit(1)

    items = []
    start = 0
    limit = 100

    while True:
        url = (
            f"https://api.zotero.org/users/{ZOTERO_USER_ID}/publications/items"
            f"?format=json&itemType=journalArticle&limit={limit}&start={start}"
        )
        req = urllib.request.Request(url)
        req.add_header("Zotero-API-Version", "3")
        if ZOTERO_API_KEY:
            req.add_header("Authorization", f"Bearer {ZOTERO_API_KEY}")

        try:
            with urllib.request.urlopen(req) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
                total = int(resp.headers.get("Total-Results", 0))
        except urllib.error.HTTPError as e:
            print(f"Error fetching from Zotero API: {e.code} {e.reason}", file=sys.stderr)
            sys.exit(1)

        items.extend(batch)
        start += limit
        if start >= total:
            break

    print(f"Fetched {len(items)} items from Zotero.")
    return items


def format_authors(creators):
    """Format author list: up to 3 authors, then 'et al.' if more."""
    authors = [c for c in creators if c.get("creatorType") == "author"]
    formatted = []
    for a in authors:
        last = a.get("lastName", a.get("name", ""))
        first = a.get("firstName", "")
        if first:
            initials = "".join(w[0] for w in first.split() if w)
            formatted.append(f"{last} {initials}")
        else:
            formatted.append(last)

    if len(formatted) > 3:
        return ", ".join(formatted[:3]) + ", et al."
    return ", ".join(formatted)


def extract_year(date_str):
    """Extract a 4-digit year from the Zotero date field."""
    if not date_str:
        return None
    match = re.search(r"\b((?:19|20)\d{2})\b", date_str)
    return int(match.group(1)) if match else None


def title_case(s):
    """Convert a string to Title Case, keeping small words lowercase.

    Handles hyphenated words, post-colon capitalization, and medical acronyms.
    """
    small_words = {
        "a", "an", "and", "as", "at", "but", "by", "for", "if", "in",
        "nor", "of", "on", "or", "so", "the", "to", "up", "via", "vs",
        "yet", "with", "from", "into", "over", "upon",
    }
    # Known uppercase tokens (medical/scientific acronyms)
    uppercase_tokens = {
        "covid", "pots", "mri", "nhl", "adhd", "adem", "nmda",
        "dna", "rna", "hiv", "aids", "copd", "icu", "ecg", "eeg",
        "ans", "cns", "pns", "emg", "bmi", "cfi", "cihr", "pecarn",
    }

    def capitalize_word(w, force_cap=False):
        """Capitalize a single word, handling hyphens and acronyms."""
        # Handle hyphenated words by capitalizing each part
        if "\u2013" in w or "-" in w:
            sep = "\u2013" if "\u2013" in w else "-"
            parts = w.split(sep)
            return sep.join(capitalize_word(p, force_cap=True) for p in parts)
        # Check for known acronyms
        if w.lower().rstrip(".,;:") in uppercase_tokens:
            return w.upper()
        # Already uppercase acronym (e.g., COVID-19 stored correctly)
        if w.isupper() and len(w) >= 2:
            return w
        if not force_cap and w.lower() in small_words:
            return w.lower()
        return w.capitalize()

    words = s.split()
    result = []
    after_colon = False
    for i, w in enumerate(words):
        force = i == 0 or i == len(words) - 1 or after_colon
        if force:
            result.append(capitalize_word(w, force_cap=True))
        else:
            result.append(capitalize_word(w))
        after_colon = w.endswith(":")
    return " ".join(result)


def format_citation(item):
    """Format a single Zotero item into the existing citation style."""
    data = item.get("data", {})
    authors = format_authors(data.get("creators", []))
    title = data.get("title", "Untitled")
    # Remove trailing period from title if present (we add our own)
    title = title.rstrip(".")
    # Convert to Title Case to match existing style
    title = title_case(title)
    # Prefer abbreviated journal name, fall back to full name
    journal = data.get("journalAbbreviation", "") or data.get("publicationTitle", "")
    year = extract_year(data.get("date", ""))
    volume = data.get("volume", "")
    issue = data.get("issue", "")
    pages = data.get("pages", "")
    # Normalize en-dashes to hyphens in page ranges
    pages = pages.replace("\u2013", "-")
    doi = data.get("DOI", "")

    # Build volume/issue/pages string
    loc = ""
    if volume:
        loc = volume
        if issue:
            loc += f"({issue})"
        if pages:
            loc += f":{pages}"

    # Assemble citation
    parts = [authors]
    parts.append(f"{title}.")
    if journal:
        parts.append(f"*{journal}*.")
    if year:
        if loc:
            parts.append(f"{year};{loc}.")
        else:
            parts.append(f"{year}.")
    if doi:
        doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        parts.append(f"[DOI]({doi_url})")

    return " ".join(parts), year


def generate_qmd(items):
    """Group items by year and write publications.qmd."""
    citations = []
    for item in items:
        text, year = format_citation(item)
        if year:
            citations.append((year, text))

    # Sort by year descending, then alphabetically within year
    citations.sort(key=lambda x: (-x[0], x[1]))

    # Group by year
    lines = [FRONT_MATTER]
    current_year = None
    for year, text in citations:
        if year != current_year:
            current_year = year
            lines.append(f"### {year}\n")
        lines.append(f"{text}\n")

    output = "\n".join(lines)
    # Clean up any triple+ blank lines
    output = re.sub(r"\n{4,}", "\n\n\n", output)

    abs_path = os.path.abspath(OUTPUT_FILE)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Wrote {len(citations)} publications to {abs_path}")


def main():
    items = fetch_items()
    if not items:
        print("No items found. publications.qmd not updated.", file=sys.stderr)
        sys.exit(1)
    generate_qmd(items)


if __name__ == "__main__":
    main()
