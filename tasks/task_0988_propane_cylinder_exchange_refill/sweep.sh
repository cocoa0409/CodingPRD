#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_0988_propane_cylinder_exchange_refill.
# All 8 rounds launch concurrently and are joined with `wait`. No early-exit.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill"
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
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL_DIR}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json, sys
d = json.load(open('$f'))
print('round $i:', 'passed=%s total=%s failed=%s' % (d.get('passed'), d.get('total'), d.get('failed', d.get('total', 0) - d.get('passed', 0))))
"
  else
    echo "round $i: MISSING results file: $f"
  fi
done
