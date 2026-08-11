#!/usr/bin/env bash
# Same 8-round stability sweep as sweep.sh, but run as 4 WAVES OF 2.
# Reason: this host is currently carrying 4-5 prd-bench-local-run processes from
# OTHER tasks. Adding a 4-wide wave on top would push the 8-core box past
# saturation and manufacture spurious "could not be restarted" ERRORs that
# masquerade as real test failures. Two-wide keeps total concurrency ~7.
#
# Usage:  nohup bash workspace/sweep2.sh > workspace/sweep.out 2>&1 &
# then foreground-poll for $IMPL/SWEEP_DONE.
#
# NEVER add an inline `pkill -f '<task path>'` here -- it self-matches this
# script's own shell and kills the sweep (exit 144, no results.json).

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0941_community_supported_fishery
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$TASK"/workspace/round.*.log "$IMPL"/SWEEP_DONE

run_round () {
  i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

for pair in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave: rounds $pair ==="
  for i in $pair; do run_round "$i" & done
  wait
done

echo "=== sweep complete ==="
touch "$IMPL/SWEEP_DONE"
