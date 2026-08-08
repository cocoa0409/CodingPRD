#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1086_multifamily_amenity_resident_experience
IMPL=$TASK/workspace/implementation
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir $TASK/test_suite \
    --isolation per-test-server \
    --timeout 120 \
    --test-timeout 30 \
    --results-file $IMPL/results.${i}.json \
    > $TASK/workspace/sweep/round.${i}.log 2>&1
}
# wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
