#!/usr/bin/env bash
# 8-round stability sweep for task_0856_septic_onsite_wastewater.
# Run as TWO WAVES OF FOUR concurrent rounds -- 8-at-once self-saturates this
# host and produces spurious boot-timeout ERRORs that look like real failures.
#
# Deliberately contains NO pkill: an inline `pkill -f '<task path>'` matches this
# script's own command line and kills its own shell (exit 144, no results.json).
#
# Usage:  bash sweep.sh
# Output: workspace/implementation/results.{1..8}.json

set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0856_septic_onsite_wastewater"
IMPL="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL}"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${TASK_DIR}/workspace/implementation && bash start.sh" \
    --test-dir      "${TASK_DIR}/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "${IMPL}/results.${i}.json" \
    > "${IMPL}/sweep.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== summary ==="
python3 - <<'PY'
import json, os
impl = "/home/ubuntu/github/CodingPRD/tasks/task_0856_septic_onsite_wastewater/workspace/implementation"
allgreen = True
for i in range(1, 9):
    p = os.path.join(impl, "results.%d.json" % i)
    if not os.path.exists(p):
        print("round %d: MISSING results file" % i); allgreen = False; continue
    d = json.load(open(p))
    s = d.get("summary", d)
    total  = s.get("total",  d.get("total"))
    passed = s.get("passed", d.get("passed"))
    failed = s.get("failed", d.get("failed"))
    errors = s.get("errors", d.get("errors"))
    print("round %d: total=%s passed=%s failed=%s errors=%s" % (i, total, passed, failed, errors))
    if passed != total or failed or errors:
        allgreen = False
        for t in d.get("tests", []):
            if t.get("outcome") not in ("passed",):
                print("    %s -> %s" % (t.get("nodeid") or t.get("name"), t.get("outcome")))
print("ALL_GREEN" if allgreen else "NOT_GREEN")
PY
