#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m pip install -q -r requirements.txt 2>/dev/null || true

export PORT="${PORT:-10000}"
exec python3 "$SCRIPT_DIR/app.py"
