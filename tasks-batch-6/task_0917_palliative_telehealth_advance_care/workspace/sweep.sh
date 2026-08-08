#!/usr/bin/env bash
# 8-round stability sweep for task_0917_palliative_telehealth_advance_care.
#
# WHY TWO WAVES OF FOUR (do not "optimize" this into one wave of 8):
#   This suite is 86 tests and the runner uses --isolation per-test-server, so each
#   round performs ~86 kill+boot cycles. Eight concurrent rounds means ~8x that peak
#   load, and past runs at this scale saw the host saturate and mass-SIGTERM the
#   pipeline (every round dying with 143 and no results.json). Four at a time is the
#   observed-safe concurrency. Wall clock cost is one extra wave, which is cheap
#   next to losing an entire sweep.
#
# WHY NO pkill ANYWHERE IN THIS FILE:
#   An inline `pkill -f '<task path>'` matches this script's own command line (the
#   path is in argv), so the sweep kills its own shell and exits 144 with no results.
#   The runner already reaps its own servers between tests. Do not add pkill.
#
# WHY A MARKER FILE:
#   A full sweep can exceed a single Bash tool-call timeout. Launch this with
#   `nohup bash sweep.sh > sweep.log 2>&1 &` and then foreground-poll for
#   implementation/SWEEP_DONE instead of blocking one tool call on the whole run.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0917_palliative_telehealth_advance_care
IMPL="$TASK_DIR/workspace/implementation"
LOGS="$TASK_DIR/workspace/round_logs"

mkdir -p "$LOGS"
rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$LOGS"/round.*.log

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$LOGS/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== wave 1 done ==="

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "=== wave 2 done ==="

ls -l "$IMPL"/results.*.json 2>/dev/null
touch "$IMPL/SWEEP_DONE"
echo "=== SWEEP COMPLETE ==="
