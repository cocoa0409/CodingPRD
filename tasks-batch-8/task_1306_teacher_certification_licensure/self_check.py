"""Self-check for the generated test suite (not part of the suite itself).

1. Every test docstring ends with exactly one Design tag resolving to a real
   instance in SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.
2. Every difficulty instance has >= 2 tests; every non-stub corner instance
   has >= 1 test (minus the documented skips); stubs have 0.
3. Every quoted "PRD ..." citation contains a >=8-word substring that survives
   a literal grep of workspace/PRD.md.
4. No pytest.mark.skip / skipif / xfail anywhere.
"""
import re
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).parent
PRD = (ROOT / "workspace" / "PRD.md").read_text()
# PRD grep modulo surrounding whitespace: normalize whitespace on both sides.
PRD_NORM = re.sub(r"\s+", " ", PRD)

diff = yaml.safe_load((ROOT / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())
corner = yaml.safe_load((ROOT / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())

diff_instances = {}  # name -> rule_id
for rule in diff["scaffold_difficulty_design"]:
    for inst in rule["instances"]:
        diff_instances[inst["name"]] = rule["rule_id"]

corner_instances = {}  # name -> (section, is_stub)
for section in corner["scaffold_corner_design"]:
    for inst in section["instances"]:
        corner_instances[inst["name"]] = (
            section["section"], "excluded_because" in inst)

SKIPPED = {
    "plan_default_then_extension_resumes",
    "plan_second_default_denies_application_and_blocks_extend",
    "traditional_without_program_rejected",
    "renewal_blocked_by_open_misconduct_case",
}

# --- collect tests ---
tag_counts = {}  # "Difficulty/rule/name" or "Corner/section/name" -> count
errors = []
test_count = 0
for path in sorted((ROOT / "test_suite").glob("test_*.py")):
    src = path.read_text()
    if re.search(r"pytest\.mark\.(skip|skipif|xfail)", src):
        errors.append(f"{path.name}: forbidden skip/xfail marker")
    # iterate test functions with their docstrings
    for m in re.finditer(
            r"def (test_\w+)\([^)]*\):\s*\n\s*\"\"\"(.*?)\"\"\"",
            src, re.S):
        test_count += 1
        name, doc = m.group(1), m.group(2)
        tags = re.findall(r"^\s*Design: (\S+)\s*$", doc, re.M)
        if len(tags) != 1:
            errors.append(f"{path.name}::{name}: expected exactly 1 Design "
                          f"tag, got {len(tags)}")
            continue
        tag = tags[0]
        parts = tag.split("/")
        if parts[0] == "Difficulty" and len(parts) == 3:
            inst = diff_instances.get(parts[2])
            if inst is None or inst != parts[1]:
                errors.append(f"{path.name}::{name}: bad difficulty tag {tag}")
                continue
        elif parts[0] == "Corner" and len(parts) == 3:
            inst = corner_instances.get(parts[2])
            if inst is None or inst[0] != parts[1]:
                errors.append(f"{path.name}::{name}: bad corner tag {tag}")
                continue
            if inst[1]:
                errors.append(f"{path.name}::{name}: tag points at stub {tag}")
                continue
        else:
            errors.append(f"{path.name}::{name}: malformed tag {tag}")
            continue
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        # PRD verbatim citation check
        quotes = re.findall(r'PRD section [\d.]+: "(.*?)"', doc, re.S)
        if not quotes:
            errors.append(f"{path.name}::{name}: no PRD citation found")
            continue
        for q in quotes:
            qnorm = re.sub(r"\s+", " ", q).strip()
            words = qnorm.split(" ")
            hit = any(" ".join(words[i:i + 8]) in PRD_NORM
                      for i in range(0, max(1, len(words) - 7)))
            if not hit:
                errors.append(
                    f"{path.name}::{name}: citation not verbatim in PRD: "
                    f"{qnorm[:90]}...")

# --- coverage ---
for iname, rule_id in diff_instances.items():
    n = tag_counts.get(f"Difficulty/{rule_id}/{iname}", 0)
    if n < 2:
        errors.append(f"difficulty instance {rule_id}/{iname}: {n} tests (<2)")
for iname, (section, is_stub) in corner_instances.items():
    n = tag_counts.get(f"Corner/{section}/{iname}", 0)
    if is_stub:
        if n != 0:
            errors.append(f"corner stub {section}/{iname}: {n} tests (!=0)")
    elif iname in SKIPPED:
        if n != 0:
            errors.append(f"skipped corner {section}/{iname}: {n} tests (!=0)")
    elif n < 1:
        errors.append(f"corner instance {section}/{iname}: {n} tests (<1)")

print(f"tests collected: {test_count}")
print(f"distinct Design tags: {len(tag_counts)}")
diff_tags = sum(1 for t in tag_counts if t.startswith("Difficulty/"))
corner_tags = sum(1 for t in tag_counts if t.startswith("Corner/"))
print(f"difficulty instances covered: {diff_tags}/{len(diff_instances)}")
print(f"corner instances covered: {corner_tags}/"
      f"{sum(1 for v in corner_instances.values() if not v[1]) - len(SKIPPED)}"
      f" (plus {len(SKIPPED)} documented skips)")
if errors:
    print("\nFAILURES:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("SELF-CHECK PASSED")
