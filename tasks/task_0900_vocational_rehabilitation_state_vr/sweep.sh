#!/bin/bash
# 8-round stability sweep as 2 waves of 4 concurrent rounds.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0900_vocational_rehabilitation_state_vr
IMPL=$TASK/workspace/implementation
TESTS=$TASK/test_suite

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TESTS \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json > $IMPL/round.${i}.log 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do
  run_round $i &
done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do
  run_round $i &
done
wait

echo "SWEEP COMPLETE"
