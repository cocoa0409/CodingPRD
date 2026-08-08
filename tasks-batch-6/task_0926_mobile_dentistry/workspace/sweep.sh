#!/usr/bin/env bash
# 8-round stability sweep for task_0926_mobile_dentistry, run as 4 WAVES OF 2.
# Waves (not 8-way concurrency) avoid host self-saturation, which produces spurious
# "could not be restarted" / boot-timeout ERRORs that masquerade as real test failures.
# NEVER add an inline `pkill -f '<task path>'` here — it self-matches this shell (exit 144).
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#         then foreground-poll for workspace/implementation/SWEEP_DONE
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0926_mobile_dentistry
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

for wave in "1 2" "3 4" "5 6" "7 8"; do
  for i in $wave; do
    run_round "$i" &
  done
  wait
  echo "wave [$wave] done"
done

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
