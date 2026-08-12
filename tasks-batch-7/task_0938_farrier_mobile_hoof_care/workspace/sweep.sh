#!/usr/bin/env bash
# 8-round stability sweep, run as 2 WAVES OF 4 concurrent rounds.
# Never 8-way concurrent (self-saturates an 8-core host and produces spurious
# "could not be restarted" ERRORs). Never inline pkill (self-matches the shell
# -> exit 144, no results.json).
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#         then foreground-poll for $IMPL/SWEEP_DONE
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0938_farrier_mobile_hoof_care
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

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== wave 1 done ==="

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "=== wave 2 done ==="

touch "$IMPL/SWEEP_DONE"
echo "=== sweep complete ==="
