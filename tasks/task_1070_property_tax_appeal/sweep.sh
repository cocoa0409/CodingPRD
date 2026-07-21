#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 concurrent rounds, to avoid
# single-task host self-saturation. No inline pkill (would self-match and
# kill the shell). Each round claims a free port via the runner's locked
# ports.tsv, so rounds do not collide.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1070_property_tax_appeal"
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

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json;d=json.load(open('$f'));print('round $i: passed=%s total=%s failed=%s'%(d.get('passed'),d.get('total'),d.get('failed')))" 2>/dev/null \
      || echo "round $i: PARSE ERROR"
  else
    echo "round $i: NO results.json"
  fi
done
