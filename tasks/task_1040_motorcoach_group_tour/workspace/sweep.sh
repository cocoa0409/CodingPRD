#!/bin/bash
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1040_motorcoach_group_tour/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_1040_motorcoach_group_tour/test_suite
rm -f $IMPL/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TESTDIR \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
done
