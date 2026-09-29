#!/bin/bash
# Per-test fresh server, like --isolation per-test-server, but lightweight.
# Usage: bash dbg_each.sh <pytest target...>
T=/home/ubuntu/github/CodingPRD/tasks/task_2362_vehicle_distribution_port_processing
PY=/home/ubuntu/.local/share/uv/tools/prd-bench-local-runner/bin/python
PORT=${DBG_PORT:-$(( 25000 + RANDOM % 5000 ))}
cd $T
IDS=$($PY -m pytest "$@" -p no:cacheprovider -q --collect-only 2>/dev/null | grep '::' | sed 's#^tasks/task_2362_vehicle_distribution_port_processing/##')
FAILED=""
for id in $IDS; do
  cd $T/workspace/implementation
  PORT=$PORT python3 app.py > /tmp/dbg_server.log 2>&1 &
  SRV=$!
  for i in $(seq 1 60); do
    curl -s -o /dev/null http://localhost:$PORT/vpc/_clock && break
    sleep 0.2
  done
  cd $T
  out=$(API_BASE_URL=http://localhost:$PORT PYTHONPATH=$T $PY -m pytest "$id" -p no:cacheprovider --tb=long -q 2>&1)
  if ! echo "$out" | grep -q "1 passed"; then
    echo "########## FAIL: $id"
    echo "$out" | head -120
    FAILED="$FAILED $id"
  fi
  kill $SRV 2>/dev/null
  wait $SRV 2>/dev/null
done
echo "=========== FAILED LIST ==========="
for f in $FAILED; do echo "$f"; done
