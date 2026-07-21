#!/usr/bin/env bash
set -u
cd /home/ubuntu/github/CodingPRD/tasks/task_1054_gift_card_platform
rm -f workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1054_gift_card_platform/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1054_gift_card_platform/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1054_gift_card_platform/workspace/implementation/results.${i}.json &
done
wait
