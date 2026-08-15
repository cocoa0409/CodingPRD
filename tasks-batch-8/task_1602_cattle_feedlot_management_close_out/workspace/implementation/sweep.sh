#!/bin/bash
# 8-round parallel stability sweep, fully detached from the calling shell.
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1602_cattle_feedlot_management_close_out/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_1602_cattle_feedlot_management_close_out/test_suite
rm -f "$IMPL"/results.*.json "$IMPL"/sweep.done
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTDIR" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep_round_${i}.log" 2>&1 &
done
wait
touch "$IMPL/sweep.done"
