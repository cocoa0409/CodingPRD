#!/usr/bin/env bash
T=/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir $T/test_suite \
    --isolation per-test-server \
    --timeout 120 --test-timeout 30 \
    --results-file $T/workspace/implementation/results.$i.json &
done
wait
