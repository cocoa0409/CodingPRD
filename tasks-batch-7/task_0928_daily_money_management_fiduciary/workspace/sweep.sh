#!/usr/bin/env bash
# 8-round stability sweep, run as 2 WAVES OF 4 to avoid host self-saturation.
# Never run 8-way concurrent. Never inline `pkill -f '<task path>'` (self-matches -> exit 144).
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0928_daily_money_management_fiduciary
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json $IMPL/SWEEP_DONE $TASK/workspace/round.*.log

run_round () {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${1}.json \
    > $TASK/workspace/round.${1}.log 2>&1
}

for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait

touch $IMPL/SWEEP_DONE
