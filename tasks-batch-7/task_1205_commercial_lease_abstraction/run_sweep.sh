#!/usr/bin/env bash
# Step 7 — 8-round parallel stability sweep for task_1205_commercial_lease_abstraction
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction"
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
python3 - <<'EOF'
import json, glob
files = sorted(glob.glob("/home/ubuntu/github/CodingPRD/tasks/task_1205_commercial_lease_abstraction/workspace/implementation/results.*.json"))
for f in files:
    try:
        d = json.load(open(f))
        print(f, "passed=", d.get("passed"), "total=", d.get("total"), "failed=", d.get("failed"))
    except Exception as e:
        print(f, "UNREADABLE:", e)
EOF
