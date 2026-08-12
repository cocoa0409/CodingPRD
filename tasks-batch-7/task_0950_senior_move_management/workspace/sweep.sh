#!/usr/bin/env bash
# 8-round stability sweep for task_0950, run as 2 waves of 4.
# Host has 8 cores and may carry a co-tenant pipeline; 8 concurrent rounds of a
# 217-test per-test-server suite self-saturates and gets rounds mass-SIGTERMed.
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
#         then foreground-poll for workspace/implementation/SWEEP_DONE
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0950_senior_move_management
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

# Waves of two rather than four: this box carries co-tenant benchmark pipelines
# that themselves run 8-way per-test-server sweeps, and the listen ports come from
# the ephemeral range, so every extra concurrent runner raises the chance that a
# sibling's keep-alive client socket squats the port during a kill-to-bind window.
for wave in "1 2" "3 4" "5 6" "7 8"; do
  for i in $wave; do run_round "$i" & done
  wait
done

touch "$IMPL/SWEEP_DONE"
