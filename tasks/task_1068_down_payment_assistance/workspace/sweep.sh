#!/bin/bash
set -u
D=/home/ubuntu/github/CodingPRD/tasks/task_1068_down_payment_assistance
rm -f "$D"/workspace/implementation/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd $D/workspace/implementation && bash start.sh" \
      --test-dir       "$D/test_suite" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$D/workspace/implementation/results.${i}.json" &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
