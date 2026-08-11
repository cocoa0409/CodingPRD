#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_0976_airport_meet_assist_wheelchair.
# All 8 rounds launch concurrently in the background and are joined with `wait`.
# No early-exit: every round runs to completion.
set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0976_airport_meet_assist_wheelchair

rm -f "${TASK_DIR}"/workspace/implementation/results.*.json
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

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json,sys; r=json.load(open('$f')); print('round $i:', r.get('passed'), '/', r.get('total'), 'failed:', r.get('failed'))"
  else
    echo "round $i: MISSING results file"
  fi
done
