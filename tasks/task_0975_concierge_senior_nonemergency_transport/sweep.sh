#!/usr/bin/env bash
# Step-7 8-round parallel stability sweep for task_0975.
# All 8 rounds launch concurrently in the background and are joined with `wait`.
# No early-exit: every round runs to completion.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport"
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
    python3 -c "import json,sys; d=json.load(open('$f')); print('round $i:', d.get('passed'), '/', d.get('total'), 'passed;', 'failed:', d.get('failed'))"
  else
    echo "round $i: MISSING results file"
  fi
done
