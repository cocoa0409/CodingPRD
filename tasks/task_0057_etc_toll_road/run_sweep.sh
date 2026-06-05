#!/usr/bin/env bash
# Internal 8-round stability sweep harness (NOT part of the shipped task).
# Runs 8 rounds in 2 batches of 4 to keep peak memory below the OOM threshold
# on this host; every round still runs to completion under per-test-server.
TASK=/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0057_etc_toll_road
IMPL=$TASK/workspace/implementation

# Deps are installed system-wide; mark so concurrent first-boots don't race on pip.
python3 -c "import flask" && touch "$IMPL/.deps_installed"

for i in 1 2 3 4 5 6 7 8; do rm -f "$IMPL/results.${i}.json"; done

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        180 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/run.${i}.log" 2>&1
}

# Batch 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# Batch 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait

echo "=== 8-round sweep results (2 batches of 4) ==="
allpass=1
for i in 1 2 3 4 5 6 7 8; do
  f="$IMPL/results.${i}.json"
  if [ -f "$f" ]; then
    read p t < <(python3 -c "import json;d=json.load(open('$f'));print(d.get('passed'),d.get('total'))")
    echo "round $i: $p / $t"
    [ "$p" = "$t" ] || allpass=0
  else
    echo "round $i: MISSING (see run.${i}.log)"
    allpass=0
  fi
done
echo "ALL_PASS=$allpass"
