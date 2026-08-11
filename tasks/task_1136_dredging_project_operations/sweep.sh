#!/bin/bash
cd /home/ubuntu/github/CodingPRD
rm -f tasks/task_1136_dredging_project_operations/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd tasks/task_1136_dredging_project_operations/workspace/implementation && bash start.sh" \
    --test-dir       tasks/task_1136_dredging_project_operations/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   tasks/task_1136_dredging_project_operations/workspace/implementation/results.${i}.json &
done
wait
