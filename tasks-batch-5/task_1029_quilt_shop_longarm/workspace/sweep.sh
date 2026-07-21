#!/bin/bash
# 8-round stability sweep run as 2 waves of 4 concurrent rounds
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1029_quilt_shop_longarm/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_1029_quilt_shop_longarm/test_suite
rm -f $IMPL/results.*.json
for wave in 1 2; do
  for k in 1 2 3 4; do
    i=$(( (wave-1)*4 + k ))
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TESTDIR \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
done
