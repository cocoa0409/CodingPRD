#!/usr/bin/env bash
# Step 7 — parallel 8-round stability sweep for task_1187.
# All 8 rounds launch concurrently and are joined with `wait`. No early exit.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1187_basement_finishing_remodel_contracting"
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL_DIR}/results.${i}.json" &
done
wait

echo "=== sweep complete ==="
ls -la "${IMPL_DIR}"/results.*.json 2>/dev/null
python3 - <<'PYEOF'
import json, glob
files = sorted(glob.glob("/home/ubuntu/github/CodingPRD/tasks/task_1187_basement_finishing_remodel_contracting/workspace/implementation/results.*.json"))
allpass = True
for fp in files:
    try:
        with open(fp) as f:
            r = json.load(f)
        p, t = r.get("passed", -1), r.get("total", -1)
        status = "PASS" if p == t else "FAIL"
        if p != t:
            allpass = False
            fails = [x for x in r.get("tests", []) if x.get("outcome") not in ("passed",)]
            print(f"{fp}: {status} passed={p} total={t}")
            for x in fails:
                print("   FAIL:", x.get("nodeid") or x.get("name"))
        else:
            print(f"{fp}: {status} passed={p} total={t}")
    except Exception as e:
        allpass = False
        print(f"{fp}: UNREADABLE {e}")
print("ALL_8_PASS" if (allpass and len(files) >= 8) else "NOT_ALL_PASS")
PYEOF
