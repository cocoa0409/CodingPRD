#!/usr/bin/env bash
# Oracle solution: stage the reference implementation into /app/implementation.
#
# Harbor's oracle agent copies the entire solution/ tree to /solution and runs
# this script. We mirror solution/implementation/ -> /app/implementation/.

set -euo pipefail

SRC=/solution/implementation
DST=/app/implementation

if [[ ! -d "$SRC" ]]; then
  echo "error: no reference implementation at $SRC" >&2
  exit 1
fi

mkdir -p "$DST"
cp -r "$SRC/." "$DST/"
chmod +x "$DST/start.sh" 2>/dev/null || true
echo "oracle: staged reference implementation into $DST"
