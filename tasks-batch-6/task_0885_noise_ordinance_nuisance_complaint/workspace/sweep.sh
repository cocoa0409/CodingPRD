#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0885_noise_ordinance_nuisance_complaint
rm -f $TASK/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.${i}.json &
done
wait
echo "SWEEP_DONE"
