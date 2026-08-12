#!/usr/bin/env bash
set -u
TD=/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification
rm -f "$TD/workspace/implementation/results."*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TD/workspace/implementation && bash start.sh" \
    --test-dir       "$TD/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TD/workspace/implementation/results.${i}.json" &
done
wait
ls -la "$TD/workspace/implementation/results."*.json
