#!/bin/bash
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_0883_mobile_vendor_sidewalk_cart_permit/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_0883_mobile_vendor_sidewalk_cart_permit/test_suite
rm -f $IMPL/results.*.json
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TESTDIR \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json
}
# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
