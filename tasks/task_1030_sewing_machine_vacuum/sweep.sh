#!/bin/bash
# Step-7 stability sweep for task_1030 — 8 rounds run as 2 waves of 4 to avoid
# host self-saturation under 4-way parallel task runs. No inline pkill (would
# self-match the sweep's own shell and exit 144). Each round claims a free port
# via the runner's file-locked registry, so waves don't collide.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1030_sewing_machine_vacuum
IMPL=$TASK_DIR/workspace/implementation
TESTS=$TASK_DIR/test_suite

rm -f "$IMPL"/results.*.json

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed=%s total=%s'%(d.get('passed'),d.get('total')))" 2>/dev/null || echo "round $i: UNREADABLE"
  else
    echo "round $i: MISSING"
  fi
done
