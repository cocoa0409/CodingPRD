#!/usr/bin/env bash
# Step 7 iteration sweep: 8 parallel rounds of prd-bench-local-run.
# Usage: bash tasks/task_0987_ice_delivery_event_ice/sweep.sh
# After completion, read results.1.json .. results.8.json under workspace/implementation/.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice

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
echo "sweep complete"
