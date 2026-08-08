#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0871_pole_attachment_joint_use
rm -f $TASK/workspace/implementation/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $TASK/workspace/implementation && bash start.sh" \
      --test-dir       $TASK/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $TASK/workspace/implementation/results.${i}.json &
  done
  wait
done
