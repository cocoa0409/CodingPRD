#!/bin/bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1052_public_adjuster
rm -f $TASK/workspace/implementation/results.*.json
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $TASK/workspace/implementation/results.${i}.json
}
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do run_round $i & done
  wait
done
