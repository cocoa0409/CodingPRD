#!/bin/bash
T=/home/ubuntu/github/CodingPRD/tasks/task_2482_money_transmitter_licensing_multistate_examination
rm -f $T/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       $T/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $T/workspace/implementation/results.$i.json \
    > $T/workspace/sweep.round$i.log 2>&1 &
done
wait
echo "SWEEP_DONE" > $T/workspace/sweep.done
