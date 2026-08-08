#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 concurrent rounds.
# Two waves (not 8 at once) to avoid self-saturating the host, which produces
# spurious boot-timeout ERRORs that look like real failures.
# NOTE: deliberately contains no pkill -- an inline pkill matching the task path
# kills its own shell (exit 144) and produces no results.json.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0854_body_art_tattoo_permit
IMPL="$TASK/workspace/implementation"

cd "$TASK" || exit 1
rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  python3 - "$IMPL/results.${i}.json" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception as e:
    print(f"{p}: UNREADABLE ({e})")
    sys.exit(0)
s = d.get("summary", d)
print(f"{p.split('/')[-1]}: total={s.get('total')} passed={s.get('passed')} "
      f"failed={s.get('failed')} errors={s.get('errors')} skipped={s.get('skipped')}")
PY
done
