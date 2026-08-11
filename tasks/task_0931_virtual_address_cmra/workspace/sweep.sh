#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR.
# Never run 8-way concurrent (self-saturates the host -> spurious "could not be
# restarted" ERRORs). Never inline `pkill -f '<task path>'` -- it self-matches
# this shell and exits 144 with no results.json. This is why the sweep lives in
# a script file and is launched with nohup, not inline.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0931_virtual_address_cmra
IMPL=$TASK/workspace/implementation
LOGS=$TASK/workspace/round_logs
mkdir -p "$LOGS"

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE
rm -f "$LOGS"/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
}

# ---- wave 1 : rounds 1-4 ----
for i in 1 2 3 4; do run_round "$i" & done
wait

# ---- wave 2 : rounds 5-8 ----
for i in 5 6 7 8; do run_round "$i" & done
wait

touch "$IMPL/SWEEP_DONE"
