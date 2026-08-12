#!/usr/bin/env bash
# 8-round parallel stability sweep for task_0974_rep_payee_professional_fiduciary.
# Every round runs to completion; no early exit. Results land in
# workspace/implementation/results.${i}.json (i = 1..8).
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0974_rep_payee_professional_fiduciary"

rm -f "${TASK_DIR}/workspace/implementation/results."*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${TASK_DIR}/workspace/implementation && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${TASK_DIR}/workspace/implementation/results.${i}.json" &
done
wait

echo "=== sweep summary ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
print('round $i: passed={passed} failed={failed} total={total}'.format(
    passed=d.get('passed','?'), failed=d.get('failed','?'), total=d.get('total','?')))
" 2>/dev/null || echo "round $i: unparsable results file $f"
  else
    echo "round $i: MISSING results file $f"
  fi
done
