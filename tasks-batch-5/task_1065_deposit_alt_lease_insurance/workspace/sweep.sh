#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1065_deposit_alt_lease_insurance
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP_DONE"
