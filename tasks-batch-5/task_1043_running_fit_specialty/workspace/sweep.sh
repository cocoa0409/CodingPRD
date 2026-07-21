#!/usr/bin/env bash
set -u
TD=/home/ubuntu/github/CodingPRD/tasks/task_1043_running_fit_specialty
IMPL=$TD/workspace/implementation
rm -f "$IMPL"/results.*.json
run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TD/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json"
}
# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "SWEEP_DONE"
