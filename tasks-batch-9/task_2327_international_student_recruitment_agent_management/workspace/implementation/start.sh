#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing.  start.sh is re-run before every per-test reboot
# (8 concurrent rounds), so the probe must not itself cost a Python interpreter
# start: a filesystem look-up for the flask package is enough, and only a real
# miss pays for the interpreter and the install.
if ! compgen -G "$HOME/.local/lib/python3*/site-packages/flask/__init__.py" >/dev/null 2>&1 \
   && ! compgen -G "/usr/lib/python3*/dist-packages/flask/__init__.py" >/dev/null 2>&1 \
   && ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
