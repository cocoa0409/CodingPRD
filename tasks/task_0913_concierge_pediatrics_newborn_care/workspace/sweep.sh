#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4.
#
# Why waves: 107 tests x per-test-server isolation = ~107 server boots per round.
# Eight concurrent rounds saturate the host and the kernel mass-SIGTERMs the
# runners (exit 143) with no results.json written. Four at a time is stable.
#
# Why a script file and not an inline shell block: an inline `pkill -f '<task path>'`
# matches the orchestrating shell's own command line and kills it (exit 144),
# leaving no results. There is no pkill here at all -- the runner reaps its own
# servers, and each round claims a free port via the runner's flock'd registry.
set -uo pipefail

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0913_concierge_pediatrics_newborn_care
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

for i in 1 2 3 4; do run_round "$i" & done
wait

for i in 5 6 7 8; do run_round "$i" & done
wait

touch "$IMPL/SWEEP_DONE"
