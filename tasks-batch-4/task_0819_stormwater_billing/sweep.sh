#!/usr/bin/env bash
# 8-round stability sweep for task_0819_stormwater_billing.
# Runs as TWO WAVES OF FOUR: a single task's 8-way concurrent sweep saturates this
# host and produces spurious "server could not be restarted" boot-timeout ERRORs
# that look like implementation bugs but are pure load artifacts.
# All 8 rounds still run to completion; take the UNION of failures across all 8.
#
# Must be run as a script file (not inlined into a Bash tool call): an inline
# `pkill -f '<task path>'` matches its own shell and kills the sweep (exit 144).

set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0819_stormwater_billing
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json

# Reap orphan servers left by any previous aborted sweep. Safe here: this is a
# script file, so the pattern cannot match the invoking shell's own command line.
pkill -f "$IMPL/app.py" 2>/dev/null
sleep 1

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do run_round "$i" & done
  wait
  pkill -f "$IMPL/app.py" 2>/dev/null
  sleep 2
done

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json, sys
p, i = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p))
except Exception as e:
    print(f"round {i}: UNREADABLE {e}"); sys.exit()
print(f"round {i}: passed={d.get('passed')} failed={d.get('failed')} error={d.get('error')} total={d.get('total')}")
PY
  else
    echo "round ${i}: MISSING results.json (see round.${i}.log)"
  fi
done
