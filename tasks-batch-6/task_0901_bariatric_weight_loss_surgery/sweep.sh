#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 concurrent rounds.
# Splitting into waves avoids host CPU/memory saturation (38 endpoints x per-test-server
# restarts x 8 concurrent rounds self-saturates a single host -> mass SIGTERM / exit 143).
# NO inline pkill anywhere (an inline `pkill -f '<task path>'` would match this script's own
# shell and self-kill -> exit 144, no results.json). The runner reaps its own per-test servers.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0901_bariatric_weight_loss_surgery"
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
    --results-file   "${IMPL}/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json;d=json.load(open('$f'));print('round $i:',d.get('passed'),'/',d.get('total'))" 2>/dev/null \
      || echo "round $i: UNPARSEABLE"
  else
    echo "round $i: MISSING"
  fi
done
