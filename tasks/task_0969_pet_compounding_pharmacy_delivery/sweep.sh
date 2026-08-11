#!/usr/bin/env bash
# 8-round parallel stability sweep for task_0969_pet_compounding_pharmacy_delivery
# Each round runs the full test suite under per-test-server isolation on its own
# auto-allocated port. All 8 rounds run concurrently and are joined with `wait`.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0969_pet_compounding_pharmacy_delivery"
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json
pids=()
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL_DIR}/results.${i}.json" &
  pids+=($!)
done
rc=0
for p in "${pids[@]}"; do
  wait "$p" || rc=1
done
exit $rc
