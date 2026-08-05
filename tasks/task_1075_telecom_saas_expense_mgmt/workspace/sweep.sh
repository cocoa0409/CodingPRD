#!/usr/bin/env bash
set -u
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1075_telecom_saas_expense_mgmt/workspace/implementation
TESTS=/home/ubuntu/github/CodingPRD/tasks/task_1075_telecom_saas_expense_mgmt/test_suite
rm -f "$IMPL"/results.*.json
run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
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
echo "SWEEP DONE"
