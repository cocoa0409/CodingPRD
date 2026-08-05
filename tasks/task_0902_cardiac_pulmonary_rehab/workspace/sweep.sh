#!/bin/bash
# 8-round sweep as 2 waves of 4 to avoid host saturation on a 52-endpoint task
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0902_cardiac_pulmonary_rehab
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json
for wave in 0 1; do
  for j in 1 2 3 4; do
    i=$((wave*4 + j))
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TASK_DIR/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
done
