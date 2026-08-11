#!/usr/bin/env bash
# 8-round stability sweep for task_0942, run as WAVES of WAVE_SIZE concurrent rounds.
#
# Usage:  bash sweep.sh [WAVE_SIZE]      # default 4  ->  2 waves of 4
#         bash sweep.sh 2                #             ->  4 waves of 2
#
# Run this from a FILE, never inline in a Bash tool call: an inline
# `pkill -f '<task path>'` matches the calling shell's own command line and
# kills it (exit 144, no results.json).  There is no pkill here at all.
#
# The script ends by touching SWEEP_DONE so the caller can launch it with
# `nohup ... &` and then foreground-poll for the marker, which keeps a sweep
# that outlives a single tool-call timeout from being orphaned.
set -uo pipefail

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0942_buying_club_food_coop
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/sweep_logs
WAVE_SIZE=${1:-4}

mkdir -p "$LOGS"
rm -f "$IMPL"/results.*.json "$LOGS"/round.*.log "$IMPL"/SWEEP_DONE

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

i=1
while [ "$i" -le 8 ]; do
  for _ in $(seq 1 "$WAVE_SIZE"); do
    [ "$i" -le 8 ] || break
    run_round "$i" &
    i=$((i+1))
  done
  wait
  echo "wave done, next round index $i, load: $(uptime)" >> "$LOGS/sweep.log"
done

touch "$IMPL/SWEEP_DONE"
