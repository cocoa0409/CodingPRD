#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0837_solid_waste_ticketing
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TASK/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
done
