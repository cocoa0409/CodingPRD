#!/bin/bash
# repro.sh <pytest args...> — fresh server per pytest invocation (mirrors the
# runner's per-test-server isolation ONLY when one test per call is used; for
# multi-test batches, restart between tests is approximated by wiping state via
# process restart per test with -f style loop).
TD=/home/ubuntu/github/CodingPRD/tasks/task_1102_household_goods_van_line_agent_network
PORT=${REPRO_PORT:-18777}

start_srv() {
  (cd $TD/workspace/implementation && PORT=$PORT exec bash start.sh) > /tmp/repro_srv.log 2>&1 &
  SRV=$!
  sleep 2
}

stop_srv() {
  kill $SRV 2>/dev/null
  wait $SRV 2>/dev/null
}

cd $TD
FAIL=0
for t in "$@"; do
  start_srv
  API_BASE_URL=http://127.0.0.1:$PORT python3 -m pytest -q "$t" 2>&1 | tail -3
  [ ${PIPESTATUS[0]} -ne 0 ] && FAIL=1
  stop_srv
done
exit $FAIL
