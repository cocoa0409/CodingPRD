#!/usr/bin/env bash
TD=/home/ubuntu/github/CodingPRD/tasks/task_1060_fundraising_gala_auction
rm -f $TD/workspace/implementation/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $TD/workspace/implementation && bash start.sh" \
      --test-dir       $TD/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $TD/workspace/implementation/results.${i}.json &
  done
  wait
done
