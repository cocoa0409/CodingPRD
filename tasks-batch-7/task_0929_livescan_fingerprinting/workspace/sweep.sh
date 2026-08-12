#!/usr/bin/env bash
# 8-round stability sweep for task_0929_livescan_fingerprinting.
#
# Run as 2 WAVES OF 4 (never 8-way concurrent): a single task's 8-way sweep
# self-saturates this 8-core host and produces spurious
# "could not be restarted"/boot-timeout ERRORs that masquerade as real test
# failures. Semantics are unchanged -- still 8 rounds, still the union of
# failures across all 8, still 8/8 passed==total to pass.
#
# There is deliberately NO inline `pkill` here: run from a script file so no
# pattern can self-match the invoking shell (that yields exit 144 and no
# results.json).
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#         then foreground-poll for workspace/implementation/SWEEP_DONE
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0929_livescan_fingerprinting
IMPL="$TASK/workspace/implementation"
TESTS="$TASK/test_suite"
LOGS="$TASK/workspace"

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE
rm -f "$LOGS"/round.*.log

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 === $(date -u +%H:%M:%S)"
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 === $(date -u +%H:%M:%S)"
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete === $(date -u +%H:%M:%S)"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL/results.${i}.json'))
t=d.get('total_tests', d.get('total'))
p=d.get('passed_tests', d.get('passed'))
print('round ${i}: passed=%s total=%s' % (p,t))
" 2>/dev/null || echo "round ${i}: UNPARSEABLE"
  else
    echo "round ${i}: MISSING results file"
  fi
done

touch "$IMPL/SWEEP_DONE"
