#!/bin/bash
# 8-round parallel stability sweep
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/test_suite

rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/implementation && bash start.sh" \
    --test-dir       "$TESTDIR" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" &
done
wait
echo "SWEEP_DONE"
ls -la "$IMPL"/results.*.json
