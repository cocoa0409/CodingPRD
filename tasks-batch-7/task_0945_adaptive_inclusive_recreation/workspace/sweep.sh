#!/usr/bin/env bash
# 8-round stability sweep, run as WAVES of WAVE_SIZE concurrent rounds.
# Usage:  bash sweep.sh [WAVE_SIZE]      (default 4)
# Launch as:  nohup bash sweep.sh 4 > sweep.out 2>&1 &
# then foreground-poll for $IMPL/SWEEP_DONE.
#
# NOTE: do NOT put any `pkill -f '<task path>'` in this file or inline in a
# Bash tool call — the pattern matches the invoking shell itself (exit 144).

set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0945_adaptive_inclusive_recreation
IMPL=$TASK/workspace/implementation
WAVE_SIZE=${1:-4}

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

i=1
while [ $i -le 8 ]; do
  hi=$(( i + WAVE_SIZE - 1 )); [ $hi -gt 8 ] && hi=8
  echo "=== wave $i..$hi  $(date -u +%H:%M:%S)"
  j=$i
  while [ $j -le $hi ]; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       "$TASK/test_suite" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$IMPL/results.${j}.json" \
      > "$TASK/workspace/round.${j}.log" 2>&1 &
    j=$(( j + 1 ))
  done
  wait
  i=$(( hi + 1 ))
done

echo "=== sweep finished $(date -u +%H:%M:%S)"
for k in 1 2 3 4 5 6 7 8; do
  python3 - "$IMPL/results.${k}.json" <<'PY'
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    rows=d.get("results") or d.get("tests") or []
    p=sum(1 for r in rows if r.get("status")=="passed")
    print(f"{sys.argv[1].split('/')[-1]}: rows={len(rows)} passed={p} failed={len(rows)-p}")
except Exception as e:
    print(f"{sys.argv[1].split('/')[-1]}: UNREADABLE {e}")
PY
done
touch "$IMPL/SWEEP_DONE"
