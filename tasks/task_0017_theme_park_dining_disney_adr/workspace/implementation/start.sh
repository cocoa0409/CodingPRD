#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q --disable-pip-version-check -r requirements.txt
exec python3 app.py
