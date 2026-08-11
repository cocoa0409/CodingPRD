#!/usr/bin/env bash
# Step 7 stability sweep: 8 parallel prd-bench-local-run rounds, per-test-server isolation.
# Each round claims its own free port via the runner's flock-based port registry.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0991_ewaste_electronics_recycling_itad
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
