#!/usr/bin/env bash
# Step-7 8-round parallel stability sweep for task_1253.
# Runs all 8 rounds concurrently, joins with wait, then blocks until all
# 8 results files exist. No early-exit: every round runs to completion.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing"
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

# Block until all 8 results files exist on disk.
until [ "$(ls "${IMPL_DIR}"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do
  sleep 20
done

echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL_DIR}/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('${IMPL_DIR}/results.${i}.json'))
t=d.get('summary',d)
print('round ${i}: passed=%s total=%s failed=%s' % (t.get('passed'), t.get('total'), t.get('failed')))
" 2>/dev/null || echo "round ${i}: results file present but unparseable"
  else
    echo "round ${i}: MISSING"
  fi
done
