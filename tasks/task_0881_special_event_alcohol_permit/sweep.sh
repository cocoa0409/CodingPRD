#!/usr/bin/env bash
# 8-round parallel stability sweep, run as 2 waves of 4 to avoid host saturation.
# No inline pkill (avoids self-match exit-144). Leaves results.{1..8}.json durable.
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0881_special_event_alcohol_permit
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    >"$IMPL/round.${i}.log" 2>&1
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
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i:', d.get('passed'),'/',d.get('total'))" 2>/dev/null \
      || echo "round $i: results.json unparseable"
  else
    echo "round $i: NO results.json"
  fi
done
