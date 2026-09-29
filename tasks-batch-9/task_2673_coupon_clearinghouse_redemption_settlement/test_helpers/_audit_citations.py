"""Developer audit: every quoted citation in the suite must appear in the PRD.

Run with:  python3 test_helpers/_audit_citations.py
It normalises whitespace on both sides so a citation wrapped across docstring
lines still matches the PRD's single-line source sentence.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRD = ROOT / "workspace" / "PRD.md"
SUITE = ROOT / "test_suite"

QUOTE = re.compile(r'"([^"]{40,})"', re.S)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    prd = normalise(PRD.read_text())
    failures = []
    tagged = 0
    untagged = []
    for path in sorted(SUITE.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            doc = ast.get_docstring(node, clean=False) or ""
            lines = [line for line in doc.strip().splitlines() if line.strip()]
            design = [line.strip() for line in lines
                      if line.strip().startswith("Design:")]
            if len(design) != 1 or not lines[-1].strip().startswith("Design:"):
                untagged.append(f"{path.name}::{node.name} -> {design}")
            else:
                tagged += 1
            body = doc
            quotes = QUOTE.findall(body)
            if not quotes:
                failures.append(f"{path.name}::{node.name} -> no citation")
            for quote in quotes:
                if normalise(quote) not in prd:
                    failures.append(
                        f"{path.name}::{node.name} -> NOT VERBATIM: "
                        f"{normalise(quote)[:110]}")
    print(f"tests with exactly one trailing Design line: {tagged}")
    for problem in untagged:
        print(f"TAG PROBLEM  {problem}")
    for problem in failures:
        print(f"CITE PROBLEM {problem}")
    return 1 if (untagged or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
