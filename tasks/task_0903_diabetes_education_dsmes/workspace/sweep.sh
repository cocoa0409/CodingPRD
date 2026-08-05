#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 concurrent rounds.
# Run from THIS script file (never inline) so no `pkill -f '<task path>'`
# can self-match the orchestrator shell (exit 144 / lost results.json).
# 45-endpoint per-test-server isolation self-saturates an 8-way concurrent
# sweep; 2 waves of 4 keeps peak load sane while still surfacing flakiness.
set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0903_diabetes_education_dsmes"
IMPL="${TASK_DIR}/workspace/implementation"
TESTS="${TASK_DIR}/test_suite"

rm -f "${IMPL}"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TESTS}" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait

# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete: 8 rounds ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL}/results.${i}.json" ]; then
    python3 - "$i" "${IMPL}/results.${i}.json" <<'PY'
import json,sys
i=sys.argv[1]; f=sys.argv[2]
try:
    d=json.load(open(f))
    p=d.get("passed"); t=d.get("total")
    fails=[x.get("name") or x.get("nodeid") for x in d.get("tests",d.get("results",[])) if (x.get("outcome") or x.get("status"))not in ("passed","pass","PASSED",True)]
    print(f"round {i}: passed={p} total={t} fails={len(fails)}")
except Exception as e:
    print(f"round {i}: PARSE-ERROR {e!r}")
PY
  else
    echo "round ${i}: NO RESULTS FILE"
  fi
done
