#!/usr/bin/env bash
# 8-round stability sweep as 2 waves of 4 (host-saturation guard).
# Leaves results.{1..8}.json durable on disk. No inline pkill (exit-144 self-kill guard).
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0884_sign_billboard_zoning_permit
IMPL=$TASK/workspace/implementation
TESTS=$TASK/test_suite

rm -f "$IMPL"/results.*.json

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    >"$IMPL/sweep.${i}.log" 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== SWEEP COMPLETE ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round ${i}: passed=%s total=%s'%(d.get('passed'),d.get('total')))" 2>/dev/null \
      || echo "round ${i}: UNPARSEABLE"
  else
    echo "round ${i}: NO RESULTS FILE"
  fi
done
