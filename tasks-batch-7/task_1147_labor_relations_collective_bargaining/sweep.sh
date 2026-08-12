#!/usr/bin/env bash
set -uo pipefail

rm -f /home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1147_labor_relations_collective_bargaining/workspace/implementation/results.${i}.json &
done
wait
