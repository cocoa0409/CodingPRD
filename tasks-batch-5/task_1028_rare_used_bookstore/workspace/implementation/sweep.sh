#!/usr/bin/env bash
# Step-7 stability sweep: 8 rounds run as 2 WAVES OF 4 concurrent rounds.
# Waves (not all-8-at-once) avoid single-task host self-saturation and reduce
# the chance of SIGTERM mass-kills when other parallel tasks sweep at the same
# time. No inline pkill (pkill -f <task path> would match this script's own
# shell → exit 144, masquerading as saturation).
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1028_rare_used_bookstore
IMPL="$TASK_DIR/workspace/implementation"
rm -f "$IMPL"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
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

echo "sweep complete"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed=%s total=%s'%(d.get('passed'),d.get('total')))" 2>/dev/null || echo "round $i: UNREADABLE"
  else
    echo "round $i: MISSING"
  fi
done
