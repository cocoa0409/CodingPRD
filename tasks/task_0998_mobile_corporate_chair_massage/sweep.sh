#!/bin/bash
# Step 7 8-round parallel stability sweep for task_0998_mobile_corporate_chair_massage
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0998_mobile_corporate_chair_massage
rm -f "$TASK_DIR"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TASK_DIR/workspace/implementation && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TASK_DIR/workspace/implementation/results.${i}.json" &
done
wait
echo "SWEEP DONE"
for i in 1 2 3 4 5 6 7 8; do
  f="$TASK_DIR/workspace/implementation/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "import json;d=json.load(open('$f'));print('round $i: passed=%s failed=%s total=%s' % (d.get('passed'),d.get('failed'),d.get('total')))"
  else
    echo "round $i: MISSING results file"
  fi
done
