#!/usr/bin/env bash
# 8-round parallel stability sweep for task_1272.
# Launches all 8 rounds concurrently, joins with wait, then exits.
# Usage: bash sweep.sh
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory"
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL_DIR}/results.${i}.json" &
done
wait

echo "SWEEP_DONE $(ls "${IMPL_DIR}"/results.*.json 2>/dev/null | wc -l) results files"
