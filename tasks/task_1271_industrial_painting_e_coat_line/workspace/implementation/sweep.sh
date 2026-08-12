#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1271_industrial_painting_e_coat_line
rm -f $TASK/workspace/implementation/results.*.json $TASK/workspace/implementation/round.*.log
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.${i}.json \
    > $TASK/workspace/implementation/round.${i}.log 2>&1 &
done
wait
