#!/usr/bin/env bash
# Durable 8-round stability sweep, run as 2 waves of 4 concurrent rounds.
# Avoids single-8-way host self-saturation (SIGTERM 143) and never uses an
# inline pkill (which self-matches the task path and exit-144 self-kills).
# Leaves results.1.json .. results.8.json on disk for the orchestrator to re-parse.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0887_property_tax_billing_collection"
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

for wave in "1 2 3 4" "5 6 7 8"; do
  for i in ${wave}; do
    run_round "${i}" &
  done
  wait
done

echo "sweep complete"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL}/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('${IMPL}/results.${i}.json'));print('round ${i}:', d.get('passed'),'/',d.get('total'))" 2>/dev/null \
      || echo "round ${i}: UNPARSEABLE"
  else
    echo "round ${i}: MISSING"
  fi
done
