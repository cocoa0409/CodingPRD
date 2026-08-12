#!/usr/bin/env bash
# Step 7 stability sweep: 8 concurrent rounds of prd-bench-local-run.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine"
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
echo "=== sweep done ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL_DIR}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json,sys; d=json.load(open('$f')); print('round $i:', 'passed=%s total=%s failed=%s' % (d.get('passed'), d.get('total'), d.get('failed')))" || echo "round $i: unparseable"
  else
    echo "round $i: MISSING results file"
  fi
done
