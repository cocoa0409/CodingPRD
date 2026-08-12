#!/usr/bin/env bash
# Step-7 parallel 8-round stability sweep for task_0971.
# All 8 rounds launch concurrently and are joined with `wait`; no early exit.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0971_adult_family_home_residential_care"
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
echo "SWEEP_DONE"
ls -1 "${IMPL_DIR}"/results.*.json 2>/dev/null | wc -l
