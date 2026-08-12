#!/usr/bin/env bash
# 8-round stability sweep, run as 2 WAVES OF 4 (never 8-way: a single task's
# 8-way concurrent sweep self-saturates the host and produces spurious
# "could not be restarted" ERRORs that masquerade as real test failures).
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
# then foreground-poll for $IMPL/SWEEP_DONE.
#
# NEVER add an inline `pkill -f '<task path>'` here -- it self-matches this
# script's own shell and kills the sweep (exit 144, no results.json).

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0941_community_supported_fishery
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$TASK"/workspace/round.*.log "$IMPL"/SWEEP_DONE

run_round () {
  i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
touch "$IMPL/SWEEP_DONE"
