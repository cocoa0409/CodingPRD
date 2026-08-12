#!/bin/bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1269_college_career_readiness_advising
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK_DIR/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json &
done
wait
