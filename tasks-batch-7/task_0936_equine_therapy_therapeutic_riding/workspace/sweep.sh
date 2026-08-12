#!/usr/bin/env bash
# 8-round stability sweep for task_0936, run as TWO WAVES OF FOUR.
# Never run 8-way concurrent (self-saturates the host -> spurious
# "API server could not be restarted" errors that masquerade as test failures).
# Never put an inline `pkill -f '<task path>'` in here: it self-matches this
# script's own shell and kills the sweep (exit 144, no results.json).
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0936_equine_therapy_therapeutic_riding
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/sweep_logs
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

for i in 1 2 3 4; do run_round "$i" & done
wait

for i in 5 6 7 8; do run_round "$i" & done
wait

touch "$IMPL/SWEEP_DONE"
