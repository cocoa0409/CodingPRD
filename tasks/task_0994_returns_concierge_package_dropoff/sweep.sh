#!/usr/bin/env bash
# Step 7 — 8-round parallel stability sweep for task_0994_returns_concierge_package_dropoff
# All 8 rounds launched concurrently in background, joined with `wait`. No early exit.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0994_returns_concierge_package_dropoff"
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

echo "=== sweep complete — per-round tallies ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL_DIR}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json, sys
d = json.load(open('$f'))
print('round $i: passed=%s failed=%s total=%s' % (d.get('passed'), d.get('failed'), d.get('total')))
" || echo "round $i: results file unparseable"
  else
    echo "round $i: MISSING results file"
  fi
done
