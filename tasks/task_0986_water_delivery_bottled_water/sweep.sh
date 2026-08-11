#!/usr/bin/env bash
# Step 7 stability sweep: 8 parallel rounds of prd-bench-local-run, per-test-server isolation.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0986_water_delivery_bottled_water"
rm -f "${TASK_DIR}/workspace/implementation/results."*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${TASK_DIR}/workspace/implementation && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${TASK_DIR}/workspace/implementation/results.${i}.json" &
done
wait
echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json,sys; d=json.load(open('$f')); print('round $i:', d.get('passed'), '/', d.get('total'), 'failed:', d.get('failed'))"
  else
    echo "round $i: MISSING results file"
  fi
done
