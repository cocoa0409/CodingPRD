#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 concurrent rounds.
# NEVER run all 8 concurrently: a single task's 8-way sweep self-saturates the
# host and produces spurious "could not be restarted" / boot-timeout ERRORs that
# masquerade as real test failures.
# NEVER put an inline `pkill -f '<task path>'` in here: the pattern self-matches
# this very shell and kills it (exit 144, no results.json).

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0927_home_inventory_valuables
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs

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

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== wave 1 done ==="

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "=== wave 2 done ==="

touch "$IMPL/SWEEP_DONE"
echo "=== SWEEP COMPLETE ==="
