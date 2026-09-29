#!/bin/bash
# Fast single-test diagnosis: fresh server per pytest invocation.
T=/home/ubuntu/github/CodingPRD/tasks/task_2362_vehicle_distribution_port_processing
PY=/home/ubuntu/.local/share/uv/tools/prd-bench-local-runner/bin/python
PORT=${DBG_PORT:-$(( 21000 + RANDOM % 4000 ))}
cd $T/workspace/implementation
PORT=$PORT python3 app.py > /tmp/dbg_server.log 2>&1 &
SRV=$!
for i in $(seq 1 50); do
  curl -s -o /dev/null http://localhost:$PORT/vpc/_clock && break
  sleep 0.2
done
cd $T
API_BASE_URL=http://localhost:$PORT PYTHONPATH=$T $PY -m pytest "$@" -p no:cacheprovider --tb=long -q 2>&1
kill $SRV 2>/dev/null
wait $SRV 2>/dev/null
