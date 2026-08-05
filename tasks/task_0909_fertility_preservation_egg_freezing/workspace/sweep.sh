#!/bin/bash
# sweep.sh — 8 rounds as 2 waves of 4
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0909_fertility_preservation_egg_freezing
IMPL="$TASK_DIR/workspace/implementation"
rm -f "$IMPL"/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       "$TASK_DIR/test_suite" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$IMPL/results.${i}.json" &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
