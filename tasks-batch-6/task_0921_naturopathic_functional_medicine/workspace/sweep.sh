#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 to avoid host saturation.
# Usage:  nohup bash sweep.sh > sweep.log 2>&1 &   then poll for $IMPL/SWEEP_DONE
# NOTE: never put a `pkill -f <task path>` inside this script's own shell — it
# self-matches and kills the sweep (exit 144, no results.json).
set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0921_naturopathic_functional_medicine
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$IMPL"/round.*.log

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

# 4 waves of 2: a co-tenant pipeline shares this 8-core host, so wave width is
# halved from the usual 4 (rule of thumb: divide wave width by concurrent pipelines).
for i in 1 2; do run_round "$i" & done
wait
for i in 3 4; do run_round "$i" & done
wait
for i in 5 6; do run_round "$i" & done
wait
for i in 7 8; do run_round "$i" & done
wait

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
