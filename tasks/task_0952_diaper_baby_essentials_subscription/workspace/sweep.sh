#!/usr/bin/env bash
# 8-round stability sweep for task_0952, run as TWO WAVES OF FOUR.
# Never 8-way concurrent (self-saturates the host and produces spurious
# "could not be restarted" boot errors). Never inline pkill (self-matches
# this script's own command line -> exit 144, no results.json).
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0952_diaper_baby_essentials_subscription
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs
mkdir -p "$LOGS"

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$LOGS"/round.*.log

run_round() {
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

# Waves of TWO. The first sweep of this task ran 4+4 and the second wave
# produced 11 scattered "could not be restarted" boot errors while the host was
# carrying ~18 foreign prd-bench runners at load ~10. Concurrency is the knob,
# so it is turned down rather than the boot timeout turned up.
for w in "1 2" "3 4" "5 6" "7 8"; do
  for i in $w; do run_round $i & done
  wait
done

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
