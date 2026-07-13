#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0841_traffic_signal_streetlight
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
# reap orphan flask servers for THIS task only (script is a separate process, safe)
pkill -f "$IMPL/app.py" 2>/dev/null || true
sleep 1
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
