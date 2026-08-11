#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR.
#
# Why waves: a single 8-way concurrent sweep self-saturates this 8-core host
# (105 tests x per-test-server isolation = ~105 server boots per round), and a
# second PRD-bench pipeline is running concurrently on the same box. Overlapping
# 8-way sweeps have previously caused mass SIGTERM (exit 143) with no results.json.
#
# Run it detached and poll for the SWEEP_DONE marker:
#   rm -f .../workspace/implementation/SWEEP_DONE
#   nohup bash .../workspace/sweep.sh > .../workspace/sweep.out 2>&1 &
#   then foreground-poll for SWEEP_DONE.
#
# NEVER put an inline `pkill -f '<task path>'` in this script or in the command
# that launches it: the pattern matches the launching shell itself, which kills
# the sweep (exit 144) before any results are written.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0932_registered_agent_compliance_calendar
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs

mkdir -p "$LOGS"
rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$LOGS"/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
}

echo "=== wave 1 (rounds 1-4) starting at $(date -u +%FT%TZ) ==="
for i in 1 2 3 4; do run_round $i & done
wait
echo "=== wave 1 done at $(date -u +%FT%TZ) ==="

echo "=== wave 2 (rounds 5-8) starting at $(date -u +%FT%TZ) ==="
for i in 5 6 7 8; do run_round $i & done
wait
echo "=== wave 2 done at $(date -u +%FT%TZ) ==="

for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p))
except Exception as e:
    print(f"{p}: UNPARSEABLE {e}"); raise SystemExit
rows=d.get("tests") or d.get("results") or []
print(f"{p.rsplit('/',1)[-1]}: passed={d.get('passed')} failed={d.get('failed')} total={d.get('total')} rows={len(rows)}")
PY
  else
    echo "results.${i}.json: MISSING"
  fi
done

touch "$IMPL/SWEEP_DONE"
echo "=== SWEEP_DONE written at $(date -u +%FT%TZ) ==="
