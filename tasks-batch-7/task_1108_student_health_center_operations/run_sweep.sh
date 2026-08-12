#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_1108_student_health_center_operations.
# All 8 rounds launch concurrently in the background and are joined with `wait`.
# Usage: bash run_sweep.sh   (exit code 0 always; inspect results.*.json for pass/fail)
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations"
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

# Print one-line summary per round
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL_DIR}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
s=d.get('summary',d)
print('round $i:', 'passed=%s total=%s failed=%s error=%s' % (s.get('passed'), s.get('total'), s.get('failed'), s.get('error')))
" 2>/dev/null || echo "round $i: (unparseable results file)"
  else
    echo "round $i: MISSING results file"
  fi
done
