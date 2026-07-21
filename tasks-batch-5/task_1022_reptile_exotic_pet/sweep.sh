#!/bin/bash
cd /home/ubuntu/github/CodingPRD/tasks/task_1022_reptile_exotic_pet
rm -f workspace/implementation/results.*.json
run_round() {
  i=$1
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1022_reptile_exotic_pet/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1022_reptile_exotic_pet/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1022_reptile_exotic_pet/workspace/implementation/results.${i}.json
}
# Wave 1
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2
for i in 5 6 7 8; do run_round $i & done
wait
