#!/bin/bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1162_emergency_board_up_property_securing
IMPL=$TASK_DIR/workspace/implementation
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/sweep_${i}.log" 2>&1 &
done
wait
until [ "$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done
echo "SWEEP DONE: $(ls "$IMPL"/results.*.json | wc -l) results files"
