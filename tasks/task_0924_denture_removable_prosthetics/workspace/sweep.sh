#!/usr/bin/env bash
# 8-round stability sweep for task_0924, run in waves to avoid host saturation.
#
# Usage:   bash workspace/sweep.sh              # default: 2 waves of 4
#          WAVE_SIZE=2 bash workspace/sweep.sh  # 4 waves of 2 (use if the host is busy
#                                               # or a previous sweep saw SIGTERM/143 kills)
#
# Launch it detached and poll for the marker rather than blocking a tool call:
#   nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#   then foreground-poll for workspace/implementation/SWEEP_DONE
#
# Do NOT add an inline `pkill -f '<task path>'` — the pattern matches this script's own
# shell and kills the sweep (exit 144, no results.json written).

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0924_denture_removable_prosthetics
IMPL=$TASK/workspace/implementation
WAVE_SIZE=${WAVE_SIZE:-4}

rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log "$IMPL"/SWEEP_DONE

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/round.${i}.log" 2>&1
}

n=0
for i in 1 2 3 4 5 6 7 8; do
  run_round "$i" &
  n=$((n + 1))
  if [ $((n % WAVE_SIZE)) -eq 0 ]; then wait; fi
done
wait

touch "$IMPL/SWEEP_DONE"
echo "sweep complete: $(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)/8 results files"
