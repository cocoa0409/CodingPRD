#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0860_eviction_diversion_portal
rm -f $TASK/workspace/implementation/results.*.json
# Wave 1: rounds 1-4
for i in 1 2 3 4; do
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.${i}.json &
done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.${i}.json &
done
wait
echo "SWEEP COMPLETE"
