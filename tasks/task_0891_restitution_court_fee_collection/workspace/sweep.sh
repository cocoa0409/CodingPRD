#!/bin/bash
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_0891_restitution_court_fee_collection/workspace/implementation
TESTS=/home/ubuntu/github/CodingPRD/tasks/task_0891_restitution_court_fee_collection/test_suite
rm -f $IMPL/results.*.json
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TESTS \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json > $IMPL/round.${i}.log 2>&1
}
# wave 1
for i in 1 2 3 4; do run_round $i & done
wait
# reap orphan flask
pkill -f "task_0891_restitution_court_fee_collection/workspace/implementation" 2>/dev/null
sleep 2
# wave 2
for i in 5 6 7 8; do run_round $i & done
wait
pkill -f "task_0891_restitution_court_fee_collection/workspace/implementation" 2>/dev/null
echo "SWEEP DONE"
