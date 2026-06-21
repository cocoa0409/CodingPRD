#!/usr/bin/env bash
# 8-round parallel stability sweep (orchestrator verification of Step 7).
# CRITICAL: --start-command MUST include the absolute `cd` because the
# per-test-server plugin re-parses it from a subprocess whose cwd is the
# test_suite dir; a bare `bash start.sh` cannot locate the script there.
set -u
IMPL=/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0397_farm_management_crop_planning/workspace/implementation
TESTDIR=/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0397_farm_management_crop_planning/test_suite
START_CMD="cd ${IMPL} && bash start.sh"

cd "${IMPL}"
rm -f results.*.json sweep.round.*.log
echo "starting 8-round parallel sweep at $(date -u +%H:%M:%S)  start_cmd=[${START_CMD}]"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "${START_CMD}" \
    --test-dir       "${TESTDIR}" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" \
    > "sweep.round.${i}.log" 2>&1 &
done
wait
echo "sweep complete at $(date -u +%H:%M:%S)"
