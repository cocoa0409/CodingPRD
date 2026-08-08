#!/bin/bash
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1091_sublet_lease_takeover_marketplace
rm -f $TASK/workspace/implementation/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd $TASK/workspace/implementation && bash start.sh" \
      --test-dir       $TASK/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $TASK/workspace/implementation/results.${i}.json &
  done
  wait
}
run_wave 1 2 3 4
pkill -f "$TASK/workspace/implementation" 2>/dev/null
sleep 1
run_wave 5 6 7 8
pkill -f "$TASK/workspace/implementation" 2>/dev/null
echo "SWEEP DONE"
