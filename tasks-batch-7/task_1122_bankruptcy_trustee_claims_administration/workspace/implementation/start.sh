#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (concurrent rounds); unconditional pip install here causes boot-time
# contention, and an import probe would add a full interpreter spawn to every
# boot. A filesystem check across the known site-packages roots is pure bash.
flask_present=0
for d in \
  "$HOME/.local/lib/python3"*/site-packages/flask \
  /usr/local/lib/python3*/site-packages/flask \
  /usr/lib/python3*/site-packages/flask \
  /usr/lib/python3*/dist-packages/flask \
  /usr/local/lib/python3*/dist-packages/flask; do
  if [ -d "$d" ]; then
    flask_present=1
    break
  fi
done
if [ "$flask_present" = "0" ]; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
