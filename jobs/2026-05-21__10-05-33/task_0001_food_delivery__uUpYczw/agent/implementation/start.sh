#!/bin/bash
set -e

cd "$(dirname "$0")"

pip install -q --disable-pip-version-check flask >/dev/null 2>&1 || pip install --disable-pip-version-check flask

export PORT="${PORT:-10000}"

exec python3 server.py
