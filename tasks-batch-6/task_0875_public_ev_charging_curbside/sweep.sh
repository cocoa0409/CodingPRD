#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 to avoid single-task host saturation.
# No inline pkill (self-match exit 144). Each round claims its own free port via the
# runner's file-locked port registry, so the 4 concurrent rounds per wave never collide.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0875_public_ev_charging_curbside"
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
    > "${IMPL}/sweep.${i}.log" 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== SWEEP COMPLETE ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL}/results.${i}.json" ]; then
    python3 -c "import json,sys; d=json.load(open('${IMPL}/results.${i}.json')); print('round ${i}: passed=%s total=%s' % (d.get('passed'), d.get('total')))" 2>/dev/null \
      || echo "round ${i}: <unparseable results.json>"
  else
    echo "round ${i}: <no results file>"
  fi
done
