#!/bin/bash
# Step 7 sweep: 8 parallel rounds of prd-bench-local-run, all launched
# concurrently and joined with wait. Run from the task directory.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1188_cosmetics_personal_care_contract"
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
echo "SWEEP_DONE"
ls -la "$TASK_DIR"/workspace/implementation/results.*.json 2>/dev/null
