#!/usr/bin/env bash
# Generic Harbor verifier for prd-bench-style tasks.
#
# This script is intentionally thin — it delegates all real work to the
# `prd-bench-local-run` CLI (installed from /tests/prd-bench-local-runner).
#
# prd-bench-local-run handles:
#   - subprocess lifecycle (start, poll-until-ready, crash detect, kill)
#   - PYTHONPATH for test_helpers and the runner package
#   - API_BASE_URL env for the test suite
#   - pytest invocation with JUnit XML
#   - parsing JUnit -> /tmp/results.json with per-test breakdown
#
# We only do two things on top of that:
#   1. install the runner + pytest deps
#   2. translate runner's results.json -> Harbor's reward.json shape
#
# Tunables (env, with defaults):
#   PORT=10000            server port (passed to start.sh via env)
#   STARTUP_TIMEOUT=60    seconds to wait for the server to respond
#   PER_TEST_TIMEOUT=10   pytest --timeout=<n> per test
#   ISOLATION=per-test-server
#                         restart the API server before each pytest test

set -uo pipefail

PORT="${PORT:-10000}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-60}"
PER_TEST_TIMEOUT="${PER_TEST_TIMEOUT:-10}"
ISOLATION="${ISOLATION:-per-test-server}"

# Harbor bind-mounts /logs/{agent,verifier} → trial_dir/{agent,verifier}, so
# anything we write here lands in the trial output. Everything else in the
# container (including /app/implementation/) dies with the container.
AGENT_DIR=/logs/agent          # agent's product: source code, trajectories
REWARD_DIR=/logs/verifier      # verifier's product: reward, test logs
REWARD_JSON="$REWARD_DIR/reward.json"
RESULTS_JSON="$REWARD_DIR/results.json"
mkdir -p "$AGENT_DIR" "$REWARD_DIR"

# Persist the agent's code FIRST, before anything else can fail. Harbor doesn't
# auto-save /app/, so without this the model's code is gone after the trial.
# Doing it up-front means a hung pytest or a crashed server doesn't cost us
# the artifact.
if [[ -d /app/implementation ]]; then
  cp -r /app/implementation "$AGENT_DIR/implementation"
  echo "[verifier] saved /app/implementation -> $AGENT_DIR/implementation"
fi

echo "[verifier] installing prd-bench-local-runner + pytest deps"
pip install --quiet -e /tests/prd-bench-local-runner pytest pytest-timeout

echo "[verifier] handing off to prd-bench-local-run"
PORT="$PORT" prd-bench-local-run \
  --start-command "cd /app/implementation && bash start.sh" \
  --test-dir       /tests/test_suite \
  --api-url        "http://localhost:${PORT}" \
  --timeout        "$STARTUP_TIMEOUT" \
  --test-timeout   "$PER_TEST_TIMEOUT" \
  --isolation      "$ISOLATION" \
  --results-file   "$RESULTS_JSON" \
  || true   # don't propagate non-zero exit; we translate it via reward.json

echo "[verifier] writing reward.json"
python3 /tests/results_to_reward.py "$RESULTS_JSON" > "$REWARD_JSON"
cat "$REWARD_JSON"
echo
