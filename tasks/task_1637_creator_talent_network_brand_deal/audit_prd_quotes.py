"""Stage 2 PRD-citation pass: every quoted span in a test docstring must
survive a whitespace-normalized substring match against PRD.md."""
import re
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/github/CodingPRD/tasks/task_1637_creator_talent_network_brand_deal")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


prd = norm((ROOT / "workspace" / "PRD.md").read_text())

problems = []
for tf in sorted((ROOT / "test_suite").glob("test_*.py")):
    src = tf.read_text()
    # Per-test chunks.
    chunks = re.split(r"(?m)^(?=\s*def test_)", src)
    for chunk in chunks:
        m = re.search(r"def (test_\w+)\(", chunk)
        if not m:
            continue
        name = m.group(1)
        doc = re.search(r'"""(.*?)"""', chunk, re.S)
        if not doc:
            problems.append(f"{tf.name}:{name}: no docstring")
            continue
        doc_text = doc.group(1)
        quotes = re.findall(r'"([^"]+)"', doc_text)
        if not quotes:
            problems.append(f"{tf.name}:{name}: no quoted PRD citation")
            continue
        for q in quotes:
            if q.startswith("Design:"):
                continue
            # Skip code-ish short spans (payload literals etc.) — only check
            # prose citations (>= 8 words).
            qn = norm(q)
            for frag in [norm(f) for f in re.split(r"\.\.\.|…", qn) if norm(f)]:
                if len(frag.split()) < 8:
                    continue
                if frag not in prd:
                    problems.append(
                        f"{tf.name}:{name}: quote not verbatim in PRD:\n    {frag[:140]}"
                    )

if problems:
    print(f"{len(problems)} PROBLEMS:")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("PRD CITATION AUDIT OK")
