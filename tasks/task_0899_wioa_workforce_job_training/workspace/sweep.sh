#!/bin/bash
T=/home/ubuntu/github/CodingPRD/tasks/task_0899_wioa_workforce_job_training
rm -f $T/workspace/implementation/results.*.json
for w in "1 2 3 4" "5 6 7 8"; do
  for i in $w; do
    prd-bench-local-run \
      --start-command "cd $T/workspace/implementation && bash start.sh" \
      --test-dir       $T/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $T/workspace/implementation/results.${i}.json &
  done
  wait
done
echo "SWEEP DONE"
