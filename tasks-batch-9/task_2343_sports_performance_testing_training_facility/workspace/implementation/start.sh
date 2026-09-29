#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing.  start.sh is re-run before every per-test reboot
# (and the stability sweep reboots eight servers in lockstep), so the probe has
# to be cheap: spawning a second interpreter just to `import flask` doubles the
# boot latency on a busy host and turns healthy boots into spurious restart
# timeouts.  A pure-shell look for the installed package costs nothing.
flask_present=""
for site in \
  "$HOME"/.local/lib/python3*/site-packages \
  /usr/local/lib/python3*/{site,dist}-packages \
  /usr/lib/python3*/{site,dist}-packages
do
  if [ -d "$site/flask" ]; then
    flask_present="yes"
    break
  fi
done

if [ -z "$flask_present" ]; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
