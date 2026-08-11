#!/usr/bin/env bash
# Step 7 stability sweep: 8 parallel rounds of prd-bench-local-run, joined with wait.
# Each round restarts the server via start.sh before every pytest test (per-test-server isolation).
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0985_firewood_bulk_fuel_delivery"
rm -f "$TASK_DIR"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TASK_DIR/workspace/implementation && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TASK_DIR/workspace/implementation/results.${i}.json" &
done
wait
