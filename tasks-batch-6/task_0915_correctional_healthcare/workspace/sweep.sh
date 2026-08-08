#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR concurrent rounds.
# Never run 8-way concurrent: a single task's 8-way sweep self-saturates this host
# and produces spurious "could not be restarted" / boot-timeout ERRORs that
# masquerade as real test failures.
# Never use inline `pkill -f '<task path>'`: it self-matches this shell (exit 144,
# no results.json). That is why this lives in a script file.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0915_correctional_healthcare
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log "$IMPL"/SWEEP_DONE

run_round () {
  i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

# ---- wave 1: rounds 1-4 ----
for i in 1 2 3 4; do run_round $i & done
wait

# ---- wave 2: rounds 5-8 ----
for i in 5 6 7 8; do run_round $i & done
wait

touch "$IMPL/SWEEP_DONE"
