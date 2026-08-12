#!/bin/bash
# Parallel 8-round stability sweep for task_1213
cd /home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program
rm -f workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/implementation/results.${i}.json &
done
wait
echo "=== sweep done ==="
for i in 1 2 3 4 5 6 7 8; do
  f=workspace/implementation/results.${i}.json
  if [ -f "$f" ]; then
    python3 -c "import json,sys; d=json.load(open('$f')); print('$i', d.get('summary', d))"
  else
    echo "$i MISSING"
  fi
done
