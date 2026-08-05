#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR concurrent rounds.
# Running all 8 at once self-saturates this host and produces spurious
# boot-timeout ERRORs. Do NOT add a pkill matching the task path here --
# it would match this script's own shell and kill the sweep (exit 144).
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0852_mosquito_abatement_district
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log

for wave in "1 2 3 4" "5 6 7 8"; do
  echo "=== wave: $wave ==="
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $IMPL && bash start.sh" \
      --test-dir      "$TASK/test_suite" \
      --isolation     per-test-server \
      --timeout       120 \
      --test-timeout  30 \
      --results-file  "$IMPL/results.$i.json" \
      > "$IMPL/round.$i.log" 2>&1 &
  done
  wait
  echo "=== wave done: $wave ==="
done

for i in 1 2 3 4 5 6 7 8; do
  python3 - "$IMPL/results.$i.json" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception as e:
    print(f"{p}: UNREADABLE ({e})"); raise SystemExit
s = d.get("summary", d)
print(f"{p.split('/')[-1]}: total={s.get('total')} passed={s.get('passed')} "
      f"failed={s.get('failed')} errors={s.get('errors')}")
PY
done
