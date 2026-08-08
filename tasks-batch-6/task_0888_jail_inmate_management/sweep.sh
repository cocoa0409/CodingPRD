#!/usr/bin/env bash
set -u
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_0888_jail_inmate_management/workspace/implementation
TESTS=/home/ubuntu/github/CodingPRD/tasks/task_0888_jail_inmate_management/test_suite
rm -f "$IMPL"/results.*.json
run_round () {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TESTS" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$1.json"
}
# 4 waves of 2 (reduced concurrency to avoid restart-health-check saturation)
for w in "1 2" "3 4" "5 6" "7 8"; do
  for i in $w; do run_round $i & done
  wait
done
echo "SWEEP DONE"
