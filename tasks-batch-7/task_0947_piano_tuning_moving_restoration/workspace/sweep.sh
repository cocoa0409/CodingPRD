#!/usr/bin/env bash
# 8-round stability sweep for task_0947, run as ceil(8/WAVE) waves of $WAVE
# concurrent rounds. Never use an inline `pkill -f <task path>` around this —
# it self-matches the invoking shell and exits 144 with no results.
#
# Usage:  WAVE=2 nohup bash sweep.sh > sweep.out 2>&1 &
#         then foreground-poll for $IMPL/SWEEP_DONE
#
# Pick WAVE from measured load (cat /proc/loadavg) AND from the number of
# FOREIGN prd-bench-local-run processes on the host:
#   load < 3 and no foreign runners -> WAVE=4
#   otherwise                       -> WAVE=2
#   heavy co-tenancy (load > 7)     -> WAVE=1 (serial)
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0947_piano_tuning_moving_restoration
IMPL=$TASK/workspace/implementation
WAVE=${WAVE:-2}

rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log "$IMPL"/SWEEP_DONE

i=1
while [ "$i" -le 8 ]; do
  pids=()
  j=0
  while [ "$j" -lt "$WAVE" ] && [ "$i" -le 8 ]; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir       "$TASK/test_suite" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$IMPL/results.${i}.json" > "$IMPL/round.${i}.log" 2>&1 &
    pids+=($!)
    i=$((i + 1))
    j=$((j + 1))
  done
  wait "${pids[@]}"
  # let dying servers release their ports before the next wave binds
  sleep 2
done

touch "$IMPL/SWEEP_DONE"
echo "sweep complete: WAVE=$WAVE"
