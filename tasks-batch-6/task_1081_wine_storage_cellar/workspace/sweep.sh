#!/usr/bin/env bash
# sweep.sh — 8-round stability sweep as 2 waves of 4
cd /home/ubuntu/github/CodingPRD/tasks/task_1081_wine_storage_cellar
rm -f workspace/implementation/results.*.json
for wave in 0 1; do
  for j in 1 2 3 4; do
    i=$(( wave*4 + j ))
    prd-bench-local-run \
      --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1081_wine_storage_cellar/workspace/implementation && bash start.sh" \
      --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1081_wine_storage_cellar/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1081_wine_storage_cellar/workspace/implementation/results.${i}.json &
  done
  wait
done
