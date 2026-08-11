#!/usr/bin/env bash
set -uo pipefail
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1164_appellate_deadline_brief_production/workspace/implementation
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1164_appellate_deadline_brief_production
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep_round_${i}.log" 2>&1 &
done
wait
echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json
with open('$IMPL/results.${i}.json') as f:
    r = json.load(f)
s = r.get('summary', r)
print('round $i:', 'passed=', s.get('passed'), 'failed=', s.get('failed'), 'total=', s.get('total'))
"
  else
    echo "round $i: NO RESULTS FILE"
  fi
done
