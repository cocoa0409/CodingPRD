#!/usr/bin/env bash
# 4-waves-of-2 stability sweep for task_1093.
# FOUR sibling tasks run their Step-7 sweeps on this same 8-core host concurrently,
# so we run our own 8 rounds as 4 sequential waves of 2 concurrent rounds each
# to avoid per-test-server boot-timeout ERRORs from host saturation.
# No inline `pkill -f '<task path>'` (that self-matches this script's own argv -> exit 144).
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1093_off_campus_student_housing"
IMPL="${TASK_DIR}/workspace/implementation"
TESTS="${TASK_DIR}/test_suite"

rm -f "${IMPL}"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TESTS}" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" \
    > "${IMPL}/round.${i}.log" 2>&1
}

# 4 waves of 2 rounds each
for wave in "1 2" "3 4" "5 6" "7 8"; do
  for i in $wave; do run_round "$i" & done
  wait
done

echo "sweep complete"
ls -1 "${IMPL}"/results.*.json 2>/dev/null | sort
