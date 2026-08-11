#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR.
#
# Why waves: 195 tests x per-test-server = ~195 server boots per round. Eight
# concurrent rounds on an 8-core host self-saturates and has previously caused
# mass SIGTERM (exit 143) of the runners. Four at a time keeps peak load sane
# while still surfacing timing-sensitive flakiness.
#
# Why a script file and not an inline command: an inline `pkill -f '<task path>'`
# matches the orchestrating shell's own cmdline and kills it (exit 144, no
# results.json). Never add an inline pkill to the caller.
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
# then poll for workspace/implementation/SWEEP_DONE.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0949_home_staging_real_estate_prep
IMPL=$TASK/workspace/implementation

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

for i in 1 2 3 4; do run_round "$i" & done
wait

for i in 5 6 7 8; do run_round "$i" & done
wait

touch "$IMPL/SWEEP_DONE"
