#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_0989.
# All 8 rounds launch concurrently in the background and are joined with `wait`.
# No early-exit: every round runs to completion.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0989_compost_pickup_organics_subscription"

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

echo "=== sweep complete; per-round summary ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${TASK_DIR}/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
p=d.get('passed',0); t=d.get('total',0)
fails=[x.get('nodeid','?') for x in d.get('tests',[]) if x.get('outcome')!='passed'] if isinstance(d.get('tests'),list) else []
print('round $i: passed=%s total=%s%s' % (p,t, (' FAILURES: '+', '.join(fails)) if p!=t else ''))
"
  else
    echo "round $i: MISSING results file $f"
  fi
done
