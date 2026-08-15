#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-invoked before every per-test
# reboot; unconditional pip install here causes boot-time contention.
# find_spec locates the package without paying for a full flask import.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
# The entry filename is deliberately task-unique: co-tenant pipelines on this
# shared host run `pkill -f "python3 app.py"`, which would otherwise SIGTERM
# this server mid-sweep and surface as spurious restart failures.
exec python3 peer_support_server.py
