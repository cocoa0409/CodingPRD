#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_1121.
# All 8 rounds launch concurrently and are joined with `wait` — no early exit.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1121_broadcast_affiliate_relations_network
IMPL="$TASK_DIR/workspace/implementation"
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" &
done
wait
echo "SWEEP_DONE $(ls "$IMPL"/results.*.json 2>/dev/null | wc -l) results files"
