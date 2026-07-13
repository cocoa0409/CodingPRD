#!/usr/bin/env bash
# Step-7 stability sweep: 8 rounds, run as 2 waves of 4.
#
# Why 2 waves of 4 and not 8-at-once: with --isolation per-test-server the runner
# boots a fresh Flask server before EVERY pytest test. 8 concurrent rounds x 58
# tests self-saturates this host and the runner starts reporting spurious
# "server could not be restarted" boot-timeout ERRORs that look exactly like
# real failures. Two waves of 4 keeps peak load survivable; wall time is ~2x a
# single round, not 8x.
#
# Why a script file and not an inline bash block: an inline `pkill -f '<task path>'`
# matches the very shell running it (the path is in its own argv), so the sweep
# kills itself -> exit 144, no results.json, masquerading as saturation.
# Running from a file keeps the task path out of the caller's argv.

set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0823_special_assessment_district"
IMPL="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL}"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" \
    > "${IMPL}/round.${i}.log" 2>&1
}

for wave in 1 2; do
  echo "=== wave ${wave} ==="
  for j in 1 2 3 4; do
    i=$(( (wave - 1) * 4 + j ))
    run_round "${i}" &
  done
  wait
done

echo "=== sweep complete ==="
python3 - <<'PY'
import json, glob, os
impl = "/home/ubuntu/github/CodingPRD/tasks/task_0823_special_assessment_district/workspace/implementation"
union = {}
for i in range(1, 9):
    p = os.path.join(impl, f"results.{i}.json")
    if not os.path.exists(p):
        print(f"round {i}: MISSING results.json")
        continue
    try:
        d = json.load(open(p))
    except Exception as e:
        print(f"round {i}: UNPARSEABLE ({e})")
        continue
    total = d.get("total"); passed = d.get("passed")
    print(f"round {i}: passed={passed} total={total}")
    for t in d.get("tests", []):
        if t.get("status") not in ("passed", "PASSED", "pass"):
            union.setdefault(t.get("name") or t.get("nodeid"), []).append(i)
print()
if union:
    print(f"UNION OF FAILING TESTS ({len(union)}):")
    for name, rounds in sorted(union.items()):
        print(f"  {name}  (failed in rounds {rounds})")
else:
    print("ALL 8 ROUNDS GREEN")
PY
