#!/usr/bin/env bash
# Step 7 iteration sweep: 8 parallel rounds of prd-bench-local-run.
# Usage: bash tasks/task_0981_pet_waste_removal_yard_service/sweep.sh
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0981_pet_waste_removal_yard_service"
rm -f "${TASK_DIR}"/workspace/implementation/results.*.json
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
echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
print('round $i:', json.dumps({k:d.get(k) for k in ('total','passed','failed','errors','skipped')}))
"
  else
    echo "round $i: MISSING results file"
  fi
done
