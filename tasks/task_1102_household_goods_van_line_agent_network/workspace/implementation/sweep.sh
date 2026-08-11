#!/bin/bash
TD=/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network
rm -f $TD/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TD/workspace/implementation && bash start.sh" \
    --test-dir       $TD/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TD/workspace/implementation/results.${i}.json > $TD/workspace/implementation/sweep.${i}.log 2>&1 &
done
wait
