#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 (dodges single-task self-saturation
# and the inline-pkill self-match exit-144 trap). No early exit; every round runs.
set -u
IMPL="/home/ubuntu/github/CodingPRD/tasks/task_1072_unclaimed_property_recovery/workspace/implementation"
TESTS="/home/ubuntu/github/CodingPRD/tasks/task_1072_unclaimed_property_recovery/test_suite"

rm -f "$IMPL"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep.${i}.log" 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "sweep complete"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed',d.get('passed'),'/',d.get('total'))" 2>/dev/null \
      || echo "round $i: results.json present but unparseable"
  else
    echo "round $i: NO results.json"
  fi
done
