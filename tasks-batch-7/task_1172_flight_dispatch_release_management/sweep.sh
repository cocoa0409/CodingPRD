#!/bin/bash
# Step 7 stability sweep — 8 parallel rounds, no early exit.
# Usage: bash sweep.sh   (from anywhere; paths are absolute)
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1172_flight_dispatch_release_management
IMPL_DIR=$TASK_DIR/workspace/implementation

rm -f "$IMPL_DIR"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL_DIR/results.${i}.json" \
    > "$IMPL_DIR/sweep_round_${i}.log" 2>&1 &
done
wait
echo "SWEEP_DONE $(ls "$IMPL_DIR"/results.*.json 2>/dev/null | wc -l) results files"
