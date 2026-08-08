#!/usr/bin/env bash
# Step-7 stability sweep: 8 rounds run as 2 WAVES OF 4 to dodge single-task
# self-saturation (an 8-way concurrent per-test-server sweep on one host
# spawns ~8x Flask boots at once and produces spurious boot-timeout ERRORs).
# No inline pkill anywhere in this file (inline `pkill -f '<task path>'` would
# self-match this script's own shell -> exit 144, no results.json).
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0874_municipal_broadband_digital_equity"
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
    --results-file   "${IMPL}/results.${i}.json" \
    > "${IMPL}/round.${i}.log" 2>&1 &
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i"; done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i"; done
wait

echo "sweep complete"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL}/results.${i}.json" ]; then
    python3 -c "import json,sys; d=json.load(open('${IMPL}/results.${i}.json')); print('round ${i}: passed=%s total=%s' % (d.get('passed'), d.get('total')))" 2>/dev/null \
      || echo "round ${i}: results.json unreadable"
  else
    echo "round ${i}: NO results.json"
  fi
done
