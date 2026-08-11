#!/usr/bin/env bash
# 8-round stability sweep for task_0948_well_water_system_service.
#
# Run this AS A SCRIPT FILE:   bash /home/ubuntu/github/CodingPRD/tasks/task_0948_well_water_system_service/sweep.sh
# Never inline its body into a Bash tool call that also contains a
# `pkill -f '<task path>'` — pkill matches the calling shell's own command
# line and kills the sweep (exit 144, no results.json).
#
# Rounds run in TWO WAVES OF FOUR, not one wave of eight. This host has 8
# cores and several co-tenant sessions; a single 8-way wave self-saturates
# and mass-kills runners with SIGTERM (143).

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0948_well_water_system_service
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json

# Reap any orphaned server from a previous sweep before starting. An orphan
# squatting a port makes the next round's bind fail and looks like a real
# test failure.
pkill -f "$IMPL/app.py" 2>/dev/null || true
sleep 1

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
  echo "round $i exited $?"
}

echo "=== wave 1: rounds 1-4  $(date +%H:%M:%S)"
for i in 1 2 3 4; do run_round "$i" & done
wait

# Reap between waves: never let wave 2 bind while wave 1's servers die.
pkill -f "$IMPL/app.py" 2>/dev/null || true
sleep 2

echo "=== wave 2: rounds 5-8  $(date +%H:%M:%S)"
for i in 5 6 7 8; do run_round "$i" & done
wait

pkill -f "$IMPL/app.py" 2>/dev/null || true

echo "=== sweep done $(date +%H:%M:%S)"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL/results.${i}.json'))
print('round ${i}: passed=%s total=%s' % (d.get('passed'), d.get('total')))
"
  else
    echo "round ${i}: NO RESULTS FILE"
  fi
done
