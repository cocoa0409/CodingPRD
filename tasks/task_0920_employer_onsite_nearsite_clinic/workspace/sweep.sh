#!/usr/bin/env bash
# 8-round stability sweep for task_0920_employer_onsite_nearsite_clinic.
#
# Pre-staged by the orchestrator. Step 7 should run this UNMODIFIED.
#
# WHY TWO WAVES OF FOUR (not 8 concurrent):
#   This host has 8 cores and other PRD-bench pipelines may be running
#   concurrently in sibling sessions. A single 8-way concurrent sweep at
#   ~90-110 tests/round with per-test-server isolation self-saturates the
#   box; prior runs saw mass SIGTERM (exit 143) with no results.json
#   produced. Two waves of four keeps peak load survivable and still
#   surfaces flakiness across 8 independent rounds.
#
# WHY NO pkill IN HERE:
#   An inline `pkill -f '<task path>'` matches this very script's own
#   command line and kills the shell running it (exit 144, no results).
#   Do NOT add one. The runner cleans up its own servers.
#
# HOW STEP 7 SHOULD INVOKE IT (a full sweep can exceed one Bash tool-call
# timeout, so do not run it in the foreground directly):
#   rm -f <impl>/SWEEP_DONE
#   nohup bash <workspace>/sweep.sh > <workspace>/sweep.log 2>&1 &
#   # then foreground-poll for the marker with a long timeout:
#   timeout 3000 bash -c 'until [ -f <impl>/SWEEP_DONE ]; do sleep 10; done'
#
# Omit --api-url: the runner claims a free port per round via its
# file-locked registry (~/.cache/prd-bench-local-runner/ports.tsv) and
# exports it as $PORT, so concurrent rounds never collide.

set -u

TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_0920_employer_onsite_nearsite_clinic"
IMPL="${TASK_DIR}/workspace/implementation"
WS="${TASK_DIR}/workspace"

rm -f "${IMPL}"/results.*.json "${IMPL}/SWEEP_DONE" "${WS}"/round.*.log

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd ${IMPL} && bash start.sh" \
    --test-dir       "${TASK_DIR}/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" \
    > "${WS}/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "${IMPL}/results.${i}.json" ]; then
    echo -n "round ${i}: "
    python3 -c "import json,sys; d=json.load(open('${IMPL}/results.${i}.json')); r=d.get('results') or d.get('tests') or []; print(d.get('passed'), '/', d.get('total'), '| rows:', len(r))" 2>/dev/null \
      || echo "(unparseable)"
  else
    echo "round ${i}: MISSING"
  fi
done

touch "${IMPL}/SWEEP_DONE"
