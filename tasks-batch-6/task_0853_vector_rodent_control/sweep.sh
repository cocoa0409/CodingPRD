#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 to avoid single-task host self-saturation.
# Run this from a directory OUTSIDE workspace/implementation (never cd into it) — a cwd
# inside the impl dir makes orphan-reap pkill patterns self-match and kill this shell.
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0853_vector_rodent_control
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       $TASK_DIR/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $IMPL/results.${i}.json \
      > $TASK_DIR/sweep.${i}.log 2>&1 &
  done
  wait
done
echo "SWEEP DONE"
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "
import json,sys
try:
    d=json.load(open('$IMPL/results.$i.json'))
    print('round $i:', d.get('passed'), '/', d.get('total'))
except Exception as e:
    print('round $i: MISSING', e)
"
done
