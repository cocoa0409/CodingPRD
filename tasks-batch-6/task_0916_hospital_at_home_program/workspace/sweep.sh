#!/usr/bin/env bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0916_hospital_at_home_program
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json $IMPL/SWEEP_DONE $TASK_DIR/workspace/round.*.log
run_round () {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK_DIR/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.$1.json \
    > $TASK_DIR/workspace/round.$1.log 2>&1
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
touch $IMPL/SWEEP_DONE
