#!/usr/bin/env bash
# 8-round stability sweep for task_0951, run as TWO WAVES OF FOUR.
#
# Why waves: 182 tests x per-test-server isolation means ~182 server boots per
# round. Eight concurrent rounds on an 8-core host self-saturates and the OS
# starts mass-SIGTERMing runners (exit 143, no results.json). Four at a time is
# the proven ceiling.
#
# Why a script file and not an inline bash block: an inline `pkill -f '<task
# path>'` matches the orchestrating shell's own command line and kills it
# (exit 144, no results). Keep all cleanup inside this file, and never pkill on
# the task path.
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
#         then foreground-poll for workspace/implementation/SWEEP_DONE
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0951_vacation_home_snowbird_concierge
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

# ---- wave 1 -------------------------------------------------------------
for i in 1 2 3 4; do run_round "$i" & done
wait

# Reap any Flask child orphaned by a killed runner. Match on the app module,
# NOT on the task path (the task path appears in this script's own argv).
pkill -f "python3 app.py" 2>/dev/null
sleep 2

# ---- wave 2 -------------------------------------------------------------
for i in 5 6 7 8; do run_round "$i" & done
wait

pkill -f "python3 app.py" 2>/dev/null

touch "$IMPL/SWEEP_DONE"
