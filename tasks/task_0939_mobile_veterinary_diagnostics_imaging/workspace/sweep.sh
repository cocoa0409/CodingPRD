#!/usr/bin/env bash
# 8-round stability sweep, run as 2 WAVES OF 4 to avoid host saturation.
#
# Why waves: a single 8-way launch at this test count (142 collected cases x
# per-test-server boots) self-saturates an 8-core host and has previously
# caused mass SIGTERM (exit 143) of sibling rounds. Two waves of 4 keeps peak
# load ~4x instead of ~8x.
#
# Why a script file and NOT inline bash: an inline `pkill -f '<task path>'`
# matches the orchestrating shell's own command line and kills it (exit 144,
# no results.json). Never add a pkill of the task path here.
#
# Ends by touching SWEEP_DONE so the caller can foreground-poll for completion
# rather than blocking a tool call for the whole sweep.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0939_mobile_veterinary_diagnostics_imaging
IMPL="$TASK/workspace/implementation"
WS="$TASK/workspace"

rm -f "$IMPL"/results.*.json "$WS"/round.*.log "$WS"/SWEEP_DONE

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$WS/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL/results.${i}.json'))
t=d.get('tests') or d.get('results') or []
p=sum(1 for x in t if x.get('status')=='passed')
print('round ${i}: total=%d passed=%d failed=%d' % (len(t), p, len(t)-p))
" 2>/dev/null || echo "round ${i}: UNPARSEABLE"
  else
    echo "round ${i}: MISSING results file"
  fi
done

touch "$WS/SWEEP_DONE"
