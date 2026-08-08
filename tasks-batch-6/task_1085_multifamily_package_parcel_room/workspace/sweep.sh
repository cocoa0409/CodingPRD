#!/bin/bash
cd /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room
rm -f workspace/implementation/results.*.json
for i in 1 2 3 4; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/workspace/implementation/results.${i}.json &
done
wait
for i in 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1085_multifamily_package_parcel_room/workspace/implementation/results.${i}.json &
done
wait
