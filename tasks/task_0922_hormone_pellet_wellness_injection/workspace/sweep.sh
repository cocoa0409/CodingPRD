#!/usr/bin/env bash
# 8-round stability sweep for task_0922, run as 4 waves of 2.
#
# Sized for a shared host: a co-tenant PRD-bench pipeline was mid-sweep at
# launch, itself running 2 concurrent runners. Launching all 8 rounds at once
# has previously mass-SIGTERMed every runner on this box. Waves of 2 keep the
# combined runner count at ~4.
#
# Run it detached and poll for the SWEEP_DONE marker; a full sweep can exceed
# a single Bash tool-call timeout:
#     nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#     # then foreground-poll for workspace/implementation/SWEEP_DONE
#
# NOTE: no inline `pkill -f '<task path>'` anywhere in this file — the pattern
# matches this script's own command line and kills the shell (exit 144) before
# results.json is written.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0922_hormone_pellet_wellness_injection
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs

mkdir -p "$LOGS"
rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$LOGS"/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
  echo "round ${i} exited rc=$?"
}

for wave in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave [$wave] starting $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  for i in $wave; do
    run_round "$i" &
  done
  wait
  echo "=== wave [$wave] done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
done

echo "=== sweep complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL/results.${i}.json'))
rows=d.get('results') or d.get('tests') or []
print('round ${i}: passed=%s total=%s rows=%d' % (d.get('passed'), d.get('total'), len(rows)))
"
  else
    echo "round ${i}: MISSING results file"
  fi
done

touch "$IMPL/SWEEP_DONE"
