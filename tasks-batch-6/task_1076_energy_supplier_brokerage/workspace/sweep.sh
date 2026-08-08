#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1076_energy_supplier_brokerage
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
run_round() {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.$1.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
