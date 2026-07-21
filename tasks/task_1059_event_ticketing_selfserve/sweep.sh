#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1059_event_ticketing_selfserve
rm -f $TASK/workspace/implementation/results.*.json
run_round() {
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.$1.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
echo SWEEP_DONE
