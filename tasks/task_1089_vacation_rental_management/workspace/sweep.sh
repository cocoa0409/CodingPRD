#!/usr/bin/env bash
# Two-waves-of-four parallel stability sweep for task_1089.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_1089_vacation_rental_management
IMPL=$TASK/workspace/implementation
TESTDIR=$TASK/test_suite

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTDIR" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

# clean stale
rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log

# wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait

# wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait

echo "SWEEP COMPLETE"
