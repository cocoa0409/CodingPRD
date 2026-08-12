#!/usr/bin/env bash
# 8-round parallel stability sweep for task_0962_archery_range_lessons_proshop
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop
IMPL_DIR=$TASK_DIR/workspace/implementation

rm -f "$IMPL_DIR"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL_DIR/results.${i}.json" &
done
wait

echo "=== sweep summary ==="
for i in 1 2 3 4 5 6 7 8; do
  f="$IMPL_DIR/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json,sys
d=json.load(open('$f'))
print('round $i:', json.dumps({k:d[k] for k in ('passed','failed','errors','total') if k in d}))
"
  else
    echo "round $i: MISSING results file"
  fi
done
