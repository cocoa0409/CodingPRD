#!/bin/bash
# Detached 8-round parallel stability sweep.
T=/home/ubuntu/github/CodingPRD/tasks/task_2362_vehicle_distribution_port_processing
rm -f $T/workspace/implementation/results.*.json $T/SWEEP_DONE
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       $T/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $T/workspace/implementation/results.${i}.json > /tmp/sweep_${i}.log 2>&1 &
done
wait
touch $T/SWEEP_DONE
