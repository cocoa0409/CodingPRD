#!/usr/bin/env bash
# 8-round stability sweep for task_0919, run as 2 waves of 4.
#
# Why waves: 102 tests x per-test-server isolation = ~102 server boots per round.
# Eight of those concurrently on an 8-core host with co-tenant pipelines has
# historically mass-SIGTERMed the runs (exit 143). Four at a time is the safe cap.
#
# Why a script file and not an inline bash block:
#   - a full sweep can exceed one Bash tool-call timeout, so this is launched
#     with `nohup ... &` and joined by foreground-polling $IMPL/SWEEP_DONE;
#   - any `pkill -f '<task path>'` written inline would match the caller's own
#     shell (the path is in its argv) and kill it -> exit 144, no results.
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#         then poll for workspace/implementation/SWEEP_DONE

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0919_transitional_care_readmission
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE
mkdir -p "$LOGS"
rm -f "$LOGS"/round.*.log

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
  echo "round ${i} exit=$?" >> "$LOGS/sweep_status.txt"
}

: > "$LOGS/sweep_status.txt"

echo "=== wave 1: rounds 1-4 === $(date -u +%FT%TZ)"
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== wave 1 done === $(date -u +%FT%TZ)"

echo "=== wave 2: rounds 5-8 === $(date -u +%FT%TZ)"
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "=== wave 2 done === $(date -u +%FT%TZ)"

cat "$LOGS/sweep_status.txt"
touch "$IMPL/SWEEP_DONE"
echo "=== SWEEP_DONE === $(date -u +%FT%TZ)"
