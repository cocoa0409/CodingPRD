#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 to avoid single-task host self-saturation.
# No inline pkill (self-match exit 144 hazard) — the runner owns per-test-server lifecycle.
set -u
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1067_flexible_rent_splitting"
IMPL="$TASK_DIR/workspace/implementation"
TESTS="$TASK_DIR/test_suite"

rm -f "$IMPL"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== SWEEP SUMMARY ==="
for i in 1 2 3 4 5 6 7 8; do
  f="$IMPL/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json
d=json.load(open('$f'))
p=d.get('passed'); t=d.get('total')
fails=[x.get('nodeid') or x.get('name') for x in d.get('tests',[]) if x.get('outcome') not in ('passed',None)]
print(f'round $i: passed={p} total={t} fails={len(fails)}')
for nf in fails: print('   FAIL', nf)
" 2>/dev/null || echo "round $i: UNPARSEABLE"
  else
    echo "round $i: NO results.json"
  fi
done
