#!/bin/bash
rm -f /home/ubuntu/github/CodingPRD/tasks/task_1036_glamping_unique_stay/workspace/implementation/results.*.json
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1036_glamping_unique_stay/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1036_glamping_unique_stay/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1036_glamping_unique_stay/workspace/implementation/results.${i}.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
