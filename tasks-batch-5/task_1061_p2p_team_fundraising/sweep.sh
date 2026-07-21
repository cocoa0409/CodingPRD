#!/usr/bin/env bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1061_p2p_team_fundraising
rm -f $TASK_DIR/workspace/implementation/results.*.json
for wave in 0 1; do
  for j in 1 2 3 4; do
    i=$(( wave * 4 + j ))
    prd-bench-local-run \
      --start-command "cd $TASK_DIR/workspace/implementation && bash start.sh" \
      --test-dir       $TASK_DIR/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $TASK_DIR/workspace/implementation/results.${i}.json &
  done
  wait
done
