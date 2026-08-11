#!/usr/bin/env bash
# 8-round stability sweep for task_0953, run as TWO WAVES OF FOUR.
# Never run 8-way concurrent: a single task's 8-way sweep self-saturates this
# 8-core host and produces spurious "could not be restarted" / boot-timeout
# ERRORs that masquerade as real test failures.
# Never put an inline `pkill -f '<task path>'` in here or in the caller: it
# self-matches this script's own shell and kills it (exit 144, no results.json).
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0953_kids_clothing_rent_swap
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

echo "wave 1 (rounds 1-4) starting at $(date -Is)"
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "wave 1 done at $(date -Is)"

echo "wave 2 (rounds 5-8) starting at $(date -Is)"
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "wave 2 done at $(date -Is)"

touch "$IMPL/SWEEP_DONE"
echo "sweep complete at $(date -Is)"
