#!/bin/bash
# sweep.sh — 8-round stability sweep, 2 waves of 4
cd /home/ubuntu/github/CodingPRD/tasks/task_0839_public_fleet_motor_pool
rm -f workspace/implementation/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_0839_public_fleet_motor_pool/workspace/implementation && bash start.sh" \
      --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_0839_public_fleet_motor_pool/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   /home/ubuntu/github/CodingPRD/tasks/task_0839_public_fleet_motor_pool/workspace/implementation/results.${i}.json &
  done
  wait
done
echo "SWEEP_DONE"
