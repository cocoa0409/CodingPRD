"""Dev-only helper: verify every test docstring's PRD quotes survive a literal
(whitespace-normalized) grep of PRD.md, and that every test carries exactly one
Design: tag. Not part of the test suite. Deleted before completion."""
import re
import sys
import ast
import pathlib

ROOT = pathlib.Path(__file__).parent
PRD = re.sub(r"\s+", " ", (ROOT / "workspace" / "PRD.md").read_text())

# Extract quoted spans from a docstring: text between double quotes.
def quoted_spans(doc):
    # join lines, normalize ws
    d = re.sub(r"\s+", " ", doc)
    return re.findall(r'"([^"]+)"', d)

problems = []
test_count = 0
tagged = 0
for f in sorted((ROOT / "test_suite").glob("test_*.py")):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            test_count += 1
            doc = ast.get_docstring(node) or ""
            tags = re.findall(r"Design: (Difficulty|Corner)/\S+", doc)
            if len(tags) != 1:
                problems.append(f"{f.name}::{node.name}: {len(tags)} Design tags")
            else:
                tagged += 1
            for span in quoted_spans(doc):
                # skip short fragments / field-only quotes
                if len(span.split()) < 6:
                    continue
                norm = re.sub(r"\s+", " ", span).strip()
                if norm not in PRD:
                    problems.append(f"{f.name}::{node.name}: NOT VERBATIM: {norm[:80]}")

print(f"tests={test_count} tagged={tagged}")
if problems:
    print("PROBLEMS:")
    for p in problems:
        print("  ", p)
    sys.exit(1)
print("all citations verbatim, all tests tagged")
