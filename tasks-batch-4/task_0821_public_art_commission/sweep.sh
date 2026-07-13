#!/usr/bin/env bash
# 8-round stability sweep, run as TWO WAVES OF FOUR.
#
# Why waves: a single task launching all 8 rounds concurrently saturates this
# host (each round restarts the Flask server before every one of 57 tests under
# --isolation per-test-server). Saturation shows up as spurious "server could
# not be restarted" boot-timeout ERRORs that look like implementation bugs but
# are pure load artifacts. Two waves of 4 keep every round's boot inside its
# timeout while still surfacing genuine flakiness across all 8 rounds.
#
# This lives in a script file on purpose: an inline `pkill -f '<task path>'`
# inside a Bash tool call matches its own shell's command line and kills it,
# yielding exit 144 and no results.json -- indistinguishable from saturation.
set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0821_public_art_commission
IMPL="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL}"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" \
    > "${IMPL}/round.${i}.log" 2>&1
}

for wave in "1 2 3 4" "5 6 7 8"; do
  for i in ${wave}; do
    run_round "${i}" &
  done
  wait
done

echo "=== SWEEP COMPLETE ==="
python3 - "${IMPL}" <<'PY'
import json, os, sys
impl = sys.argv[1]
for i in range(1, 9):
    p = os.path.join(impl, f"results.{i}.json")
    if not os.path.exists(p):
        print(f"round {i}: MISSING results.json")
        continue
    try:
        r = json.load(open(p))
    except Exception as e:
        print(f"round {i}: UNREADABLE ({e})")
        continue
    passed = r.get("passed"); total = r.get("total")
    fails = [t.get("name") for t in r.get("tests", []) if t.get("status") not in ("passed", "PASSED")]
    print(f"round {i}: passed={passed} total={total}" + (f" FAILING={fails}" if fails else ""))
PY
