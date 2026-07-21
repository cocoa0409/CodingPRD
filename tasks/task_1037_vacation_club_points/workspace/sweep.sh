#!/bin/bash
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1037_vacation_club_points/workspace/implementation
TESTS=/home/ubuntu/github/CodingPRD/tasks/task_1037_vacation_club_points/test_suite
rm -f $IMPL/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TESTS \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
