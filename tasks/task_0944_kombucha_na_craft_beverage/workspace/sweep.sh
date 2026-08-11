#!/usr/bin/env bash
# Pre-staged 8-round stability sweep for task_0944.
#
# Run it as:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
# then FOREGROUND-poll for workspace/SWEEP_DONE (a full sweep can exceed one
# Bash tool-call timeout).  Never inline `pkill -f '<task path>'` in the caller:
# the pattern matches the caller's own shell and kills it (exit 144, no
# results.json).  This script does no pkill at all — the runner owns process
# lifecycle via per-test-server isolation.
#
# WAVE controls how many rounds run concurrently.  This host is shared with
# sibling PRD-bench pipelines; overlapping sweeps have previously mass-killed
# each other with SIGTERM (143).  Count FOREIGN `prd-bench-local-run` processes
# (not just load average) before raising it.  Default 2 (4 waves); 4 only when
# the host is measurably idle; 1 (fully serial) when co-tenants are sweeping.
set -uo pipefail

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0944_kombucha_na_craft_beverage
IMPL=$TASK/workspace/implementation
WS=$TASK/workspace
WAVE=${WAVE:-2}

rm -f "$IMPL"/results.*.json "$WS"/round.*.log "$WS"/SWEEP_DONE

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$WS/round.${i}.log" 2>&1
}

i=1
while [ "$i" -le 8 ]; do
  j=0
  pids=()
  while [ "$j" -lt "$WAVE" ] && [ "$i" -le 8 ]; do
    run_round "$i" &
    pids+=("$!")
    echo "launched round $i (pid ${pids[-1]})"
    i=$((i+1)); j=$((j+1))
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "wave done; load: $(cut -d' ' -f1-3 /proc/loadavg)"
done

echo "sweep complete"
ls -la "$IMPL"/results.*.json 2>/dev/null | wc -l
touch "$WS/SWEEP_DONE"
