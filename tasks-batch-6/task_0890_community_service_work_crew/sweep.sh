#!/bin/bash
# 8-round stability sweep as 2 waves of 4 concurrent rounds
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_0890_community_service_work_crew/workspace/implementation
TESTS=/home/ubuntu/github/CodingPRD/tasks/task_0890_community_service_work_crew/test_suite
rm -f "$IMPL"/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       "$TESTS" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$IMPL/results.${i}.json" &
  done
  wait
done
