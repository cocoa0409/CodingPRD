#!/usr/bin/env bash
# 8-round stability sweep, run as WAVES of concurrent rounds (never 8-way).
# Usage: nohup bash sweep.sh [WAVE_SIZE] > sweep.log 2>&1 &
#        then foreground-poll for $IMPL/SWEEP_DONE
# Never put an inline `pkill -f <task path>` anywhere near this: it self-matches
# this very script's command line and kills the shell (exit 144, no results).

set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0946_mobile_knife_tool_sharpening
IMPL=$TASK/workspace/implementation
WAVE=${1:-4}

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

i=1
while [ $i -le 8 ]; do
  n=0
  while [ $n -lt "$WAVE" ] && [ $i -le 8 ]; do
    run_round $i &
    i=$((i+1)); n=$((n+1))
  done
  wait
done

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
