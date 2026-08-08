#!/usr/bin/env bash
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0910_mens_health_hormone_clinic
rm -f "$TASK"/workspace/implementation/results.*.json
run_round () {
  prd-bench-local-run \
    --start-command "cd $TASK/workspace/implementation && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TASK/workspace/implementation/results.${1}.json"
}
# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "SWEEP_DONE"
