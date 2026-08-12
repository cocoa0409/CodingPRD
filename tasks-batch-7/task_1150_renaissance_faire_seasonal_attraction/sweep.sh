#!/usr/bin/env bash
# Step 7 — 8-round parallel stability sweep.
# Usage: bash sweep.sh
# Launches 8 concurrent prd-bench-local-run rounds (fresh results.*.json each),
# waits for all, then prints a per-round PASS/FAIL summary.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1150_renaissance_faire_seasonal_attraction"
IMPL="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL}"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" &
done
wait

echo "=== sweep summary ==="
total_fail=0
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL}/results.${i}.json"
  if [ ! -f "$f" ]; then
    echo "round ${i}: MISSING results file"
    total_fail=1
    continue
  fi
  python3 - "$f" "$i" <<'PYEOF'
import json, sys
f, i = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(f))
except Exception as e:
    print(f"round {i}: UNREADABLE ({e})"); sys.exit(0)
passed = d.get('passed', d.get('summary', {}).get('passed', '?'))
total = d.get('total', d.get('summary', {}).get('total', '?'))
failed = d.get('failed', d.get('summary', {}).get('failed', '?'))
print(f"round {i}: passed={passed} failed={failed} total={total}")
PYEOF
done
exit $total_fail
