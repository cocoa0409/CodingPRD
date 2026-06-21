#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Only install deps if Flask isn't already importable. Reinstalling on every
# per-test-server restart serializes 8 concurrent rounds on pip's site-packages
# lock and starves the per-test boot window.
python3 -c "import flask" 2>/dev/null || python3 -m pip install -q -r requirements.txt
exec python3 app.py
