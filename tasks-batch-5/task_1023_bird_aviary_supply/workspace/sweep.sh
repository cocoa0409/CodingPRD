#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1023_bird_aviary_supply
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TASK/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
echo "SWEEP_DONE"
