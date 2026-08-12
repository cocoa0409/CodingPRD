#!/bin/bash
# Step 7 — parallel 8-round stability sweep for task_1000_fitness_wellness_reimbursement_benefit
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1000_fitness_wellness_reimbursement_benefit

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
