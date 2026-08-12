#!/usr/bin/env bash
rm -f /home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1191_grain_cooperative_patronage_member_equity/workspace/implementation/results.${i}.json &
done
wait
