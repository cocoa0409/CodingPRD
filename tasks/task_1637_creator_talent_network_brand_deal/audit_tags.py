"""Stage 2 self-audit: tag integrity + coverage against the two design yamls."""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path("/home/ubuntu/github/CodingPRD/tasks/task_1637_creator_talent_network_brand_deal")

diff = yaml.safe_load((ROOT / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())[
    "scaffold_difficulty_design"
]
corner = yaml.safe_load((ROOT / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())[
    "scaffold_corner_design"
]

difficulty_instances = {}  # "Difficulty/<rule>/<name>" -> count needed
for rule in diff:
    for inst in rule["instances"]:
        difficulty_instances[f"Difficulty/{rule['rule_id']}/{inst['name']}"] = 2

corner_instances = {}
corner_stubs = set()
for section in corner:
    for inst in section["instances"]:
        key = f"Corner/{section['section']}/{inst['name']}"
        if "excluded_because" in inst:
            corner_stubs.add(key)
        else:
            corner_instances[key] = 1

# Collect tags per test function.
tag_counts = {}
test_files = sorted((ROOT / "test_suite").glob("test_*.py"))
n_tests = 0
problems = []
func_re = re.compile(r"^\s*def (test_\w+)\(", re.M)
for tf in test_files:
    src = tf.read_text()
    funcs = func_re.findall(src)
    n_tests += len(funcs)
    # Split source by test function to check tag count per test.
    chunks = re.split(r"(?m)^(?=\s*def test_)", src)
    for chunk in chunks:
        m = re.search(r"def (test_\w+)\(", chunk)
        if not m:
            continue
        full_tags = re.findall(r"Design: ((?:Difficulty|Corner)/\S+)", chunk)
        if len(full_tags) != 1:
            problems.append(
                f"{tf.name}:{m.group(1)} has {len(full_tags)} Design tags"
            )
            continue
        tag_counts[full_tags[0]] = tag_counts.get(full_tags[0], 0) + 1

# 1. Every tag resolves to a real instance; stubs must have zero tests.
for tag, n in tag_counts.items():
    if tag in corner_stubs:
        problems.append(f"STUB has a test: {tag}")
    elif tag not in difficulty_instances and tag not in corner_instances:
        problems.append(f"UNRESOLVED tag: {tag}")

# 2. Coverage: every difficulty instance >= 2, every non-stub corner >= 1.
for tag, need in difficulty_instances.items():
    have = tag_counts.get(tag, 0)
    if have < need:
        problems.append(f"DIFFICULTY shortfall {tag}: {have} < {need}")
for tag, need in corner_instances.items():
    have = tag_counts.get(tag, 0)
    if have < need:
        problems.append(f"CORNER shortfall {tag}: {have} < {need}")

# 3. Stub cross-references resolve to difficulty instances.
for section in corner:
    for inst in section["instances"]:
        if "excluded_because" in inst:
            ref = inst["excluded_because"]["difficulty_instance"]
            if not any(
                ref == i["name"]
                for rule in diff
                for i in rule["instances"]
            ):
                problems.append(
                    f"broken stub xref: {inst['name']} -> {ref}"
                )

print(f"test functions: {n_tests}")
print(f"difficulty instances: {len(difficulty_instances)} (need >=2 each)")
print(f"corner non-stub instances: {len(corner_instances)} (need >=1 each)")
print(f"corner stubs (untranslated): {len(corner_stubs)}")
if problems:
    print("PROBLEMS:")
    for p in sorted(problems):
        print(" -", p)
    sys.exit(1)
print("AUDIT OK")
