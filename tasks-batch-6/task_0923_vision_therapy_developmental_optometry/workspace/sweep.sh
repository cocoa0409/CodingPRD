#!/usr/bin/env bash
# 8-round stability sweep for task_0923, run as 4 waves of 2.
#
# Why waves: this host carries several concurrent PRD-bench pipelines. Launching
# all 8 rounds at once has previously mass-SIGTERMed rounds (exit 143) on a
# saturated box. 4 waves of 2 keeps peak load bounded while still running every
# round to completion. There is NO early exit — all 8 rounds always run.
#
# Do NOT add an inline `pkill -f <task path>` here: the pattern matches this
# script's own command line and kills the shell (exit 144, no results.json).
#
# Usage:  nohup bash sweep.sh > sweep.out 2>&1 &
#         then foreground-poll for $IMPL/SWEEP_DONE
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0923_vision_therapy_developmental_optometry
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

for wave in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave $wave starting $(date -u +%H:%M:%S) ==="
  for i in $wave; do run_round "$i" & done
  wait
  echo "=== wave $wave done     $(date -u +%H:%M:%S) ==="
done

echo "=== all 8 rounds complete $(date -u +%H:%M:%S) ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL/results.${i}.json'))
rows=d.get('tests') or d.get('results') or []
p=sum(1 for r in rows if str(r.get('status','')).lower()=='passed')
print('round ${i}: rows=%d passed=%d  summary=%s' % (len(rows), p, {k:v for k,v in d.items() if isinstance(v,(int,str))}))
" 2>/dev/null || echo "round ${i}: unparseable"
  else
    echo "round ${i}: MISSING results file"
  fi
done

touch "$IMPL/SWEEP_DONE"
