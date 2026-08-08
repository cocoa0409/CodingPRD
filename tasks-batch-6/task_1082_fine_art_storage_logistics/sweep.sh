#!/usr/bin/env bash
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1082_fine_art_storage_logistics
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json
run_round() {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK_DIR/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.$1.json
}
# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
