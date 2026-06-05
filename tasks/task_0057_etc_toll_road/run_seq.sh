#!/usr/bin/env bash
# Run rounds 5-8 sequentially (peak memory = 1 runner + 1 server) to complete
# the 8-round stability evidence without the OOM kills the 8x/4x bursts hit on
# this host. Rounds 1-4 already passed 69/69 in batch 1.
TASK=/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0057_etc_toll_road
IMPL=$TASK/workspace/implementation
python3 -c "import flask" && touch "$IMPL/.deps_installed"

for i in 5 6 7 8; do
  rm -f "$IMPL/results.${i}.json"
  pkill -9 -f "implementation/app.py" 2>/dev/null; sleep 1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        180 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/run.${i}.log" 2>&1
  read p t < <(python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print(d.get('passed'),d.get('total'))" 2>/dev/null || echo "ERR ERR")
  echo "round $i: $p / $t"
done

echo "=== full 8-round summary ==="
allpass=1
for i in 1 2 3 4 5 6 7 8; do
  f="$IMPL/results.${i}.json"
  if [ -f "$f" ]; then
    read p t < <(python3 -c "import json;d=json.load(open('$f'));print(d.get('passed'),d.get('total'))")
    echo "round $i: $p / $t"
    [ "$p" = "$t" ] || allpass=0
  else
    echo "round $i: MISSING"; allpass=0
  fi
done
echo "ALL_PASS=$allpass"
