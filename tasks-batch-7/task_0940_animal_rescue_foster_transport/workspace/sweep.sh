#!/usr/bin/env bash
# 8-round stability sweep, run as 2 WAVES OF 4 concurrent rounds.
# Never 8-way concurrent: a single task's 8-way sweep self-saturates the host and
# produces spurious "could not be restarted" ERRORs that masquerade as test failures.
# Never inline `pkill -f '<task path>'`: it self-matches this shell -> exit 144, no results.
# The --start-command MUST keep the verbatim "cd <impl> && bash start.sh" prefix.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0940_animal_rescue_foster_transport
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

echo "wave 1: rounds 1-4  ($(date -u +%FT%TZ))"
for i in 1 2 3 4; do run_round $i & done
wait

echo "wave 2: rounds 5-8  ($(date -u +%FT%TZ))"
for i in 5 6 7 8; do run_round $i & done
wait

echo "sweep complete ($(date -u +%FT%TZ))"
touch "$IMPL/SWEEP_DONE"
