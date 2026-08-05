#!/usr/bin/env bash
# 8-round stability sweep for task_0925_dental_sleep_medicine.
# Run as 4 waves of 2 — a co-tenant pipeline is live on this host and a single
# 8-way launch has historically mass-SIGTERMed every round (exit 143).
# Launch with:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
# then foreground-poll for $IMPL/SWEEP_DONE.  Never inline `pkill -f <task path>`
# from the same shell — it self-matches and exits 144 with no results.json.

set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0925_dental_sleep_medicine
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

for wave in "1 2" "3 4" "5 6" "7 8"; do
  for i in $wave; do run_round "$i" & done
  wait
done

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
