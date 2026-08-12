#!/usr/bin/env bash
# 8-round parallel stability sweep for task_0963_indoor_playground_kids_cafe
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe
rm -f "${TASK_DIR}/workspace/implementation/results."*.json
pids=()
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${TASK_DIR}/workspace/implementation && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${TASK_DIR}/workspace/implementation/results.${i}.json" \
    > "${TASK_DIR}/sweep_round_${i}.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do
  wait "$p"
done
echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
print('round $i:', 'passed={passed}/{total} failed={failed} errors={errors}'.format(
  passed=d.get('passed','?'), total=d.get('total','?'),
  failed=d.get('failed','?'), errors=d.get('errors','?')))
"
  else
    echo "round $i: MISSING results file"
  fi
done
