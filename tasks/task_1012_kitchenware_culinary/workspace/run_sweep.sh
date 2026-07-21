#!/usr/bin/env bash
set -u
cd /home/ubuntu/github/CodingPRD/tasks/task_1012_kitchenware_culinary
rm -f workspace/implementation/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1012_kitchenware_culinary/workspace/implementation && bash start.sh" \
      --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1012_kitchenware_culinary/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1012_kitchenware_culinary/workspace/implementation/results.${i}.json &
  done
  wait
done
