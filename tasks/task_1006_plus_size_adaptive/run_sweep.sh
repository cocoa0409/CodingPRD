#!/bin/bash
rm -f /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/workspace/implementation/results.*.json
# Wave 1: rounds 1-4
for i in 1 2 3 4; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/workspace/implementation/results.${i}.json &
done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1006_plus_size_adaptive/workspace/implementation/results.${i}.json &
done
wait
