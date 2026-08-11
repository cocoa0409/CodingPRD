#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 concurrent rounds.
# Never 8-way concurrent (host self-saturation); never an inline pkill (self-match -> exit 144).
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0934_smart_home_support_subscription
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/sweeplogs
mkdir -p "$LOGS"
rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$LOGS"/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
}

for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait

touch "$IMPL/SWEEP_DONE"
