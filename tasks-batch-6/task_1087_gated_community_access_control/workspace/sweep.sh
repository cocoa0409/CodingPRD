#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1087_gated_community_access_control
rm -f $TASK/workspace/implementation/results.*.json
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
echo "SWEEP DONE"
