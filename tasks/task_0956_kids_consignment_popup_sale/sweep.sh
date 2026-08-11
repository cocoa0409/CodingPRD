#!/usr/bin/env bash
# 8-round parallel stability sweep for task_0956_kids_consignment_popup_sale.
# Every round runs to completion (no early-exit). Results land in
# workspace/implementation/results.{1..8}.json.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0956_kids_consignment_popup_sale"
rm -f "${TASK_DIR}/workspace/implementation/results."*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${TASK_DIR}/workspace/implementation && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${TASK_DIR}/workspace/implementation/results.${i}.json" \
    > "${TASK_DIR}/workspace/implementation/sweep_round_${i}.log" 2>&1 &
done
wait
echo "sweep complete"
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json;d=json.load(open('$f'));print('round $i:', d.get('passed'), '/', d.get('total'))"
  else
    echo "round $i: MISSING results file"
  fi
done
