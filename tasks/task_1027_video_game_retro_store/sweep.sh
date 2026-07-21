#!/usr/bin/env bash
# Step-7 stability sweep for task_1027_video_game_retro_store.
# Runs the 8-round sweep as 2 WAVES OF 4 concurrent rounds to avoid host
# self-saturation / SIGTERM mass-kill when 4 parallel tasks sweep at once.
# No inline pkill (would self-match and exit 144). Run from this file, not inline.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1027_video_game_retro_store"
IMPL="${TASK_DIR}/workspace/implementation"
TESTS="${TASK_DIR}/test_suite"

rm -f "${IMPL}"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TESTS}" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "SWEEP_DONE"
