#!/usr/bin/env bash
# Step 7 stability sweep: 8 parallel rounds of prd-bench-local-run.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1157_water_meter_replacement_capital_program"
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
echo "SWEEP_DONE"
ls -la "${IMPL}"/results.*.json
