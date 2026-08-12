#!/bin/bash
# Step 7 stability sweep: 8 parallel rounds of prd-bench-local-run.
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0978_accessibility_ramp_home_modification
IMPL=$TASK_DIR/workspace/implementation
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
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
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i:', d.get('passed'), '/', d.get('total'), 'failed:', d.get('failed'))"
  else
    echo "round $i: NO RESULTS FILE"
  fi
done
