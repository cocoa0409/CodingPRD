#!/usr/bin/env bash
# Step-7 stability sweep for task_1096 — 8 rounds run as 4 WAVES OF 2.
# Four sibling tasks sweep this same 8-core host concurrently; launching all 8
# rounds at once saturates boots and yields spurious per-test-server ERRORs.
# Run from a script FILE (never inline) so no `pkill -f <path>` can self-match
# the sweep's own shell (exit 144, empty results).
set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1096_travel_nurse_locum_tenens
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep.${i}.log" 2>&1
}

# 4 waves of 2 rounds each: (1,2) (3,4) (5,6) (7,8)
for wave in "1 2" "3 4" "5 6" "7 8"; do
  for i in $wave; do
    run_round "$i" &
  done
  wait
done

echo "SWEEP_DONE"
