#!/usr/bin/env bash
# Step-7 stability sweep for task_1094 — 4 WAVES of 2 rounds each.
# Host-saturation mitigation: FOUR sibling tasks sweep this same 8-core host
# concurrently, so we NEVER launch all 8 rounds at once. Two rounds per wave,
# join each wave before starting the next.
#
# Reaps only THIS task's orphan Flask servers between waves, matched by cwd
# (never a bare `pkill -f python3`, which would self-kill this script's shell).
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1094_senior_living_placement_referral"
IMPL="$TASK_DIR/workspace/implementation"
TESTS="$TASK_DIR/test_suite"

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

reap_orphans() {
  # Kill only leftover servers whose cwd is THIS task's implementation dir.
  for pid in $(pgrep -f "start.sh" 2>/dev/null); do
    local cwd
    cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
    if [ "$cwd" = "$IMPL" ]; then kill "$pid" 2>/dev/null || true; fi
  done
  # Also reap python app processes rooted in this impl dir.
  for pid in $(pgrep -f "$IMPL" 2>/dev/null); do
    kill "$pid" 2>/dev/null || true
  done
}

for wave in "1 2" "3 4" "5 6" "7 8"; do
  set -- $wave
  a="$1"; b="$2"
  echo "=== wave: rounds $a $b ==="
  run_round "$a" &
  p1=$!
  run_round "$b" &
  p2=$!
  wait "$p1" "$p2"
  reap_orphans
  sleep 2
done

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json,sys; d=json.load(open('$IMPL/results.${i}.json')); print('round $i: passed=%s total=%s' % (d.get('passed'), d.get('total')))" 2>/dev/null \
      || echo "round $i: results file unreadable"
  else
    echo "round $i: NO results file"
  fi
done
