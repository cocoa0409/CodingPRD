#!/usr/bin/env bash
# Thin wrapper around harbor_tasks/_lib/prepare.sh. All real logic lives there.
set -euo pipefail
exec "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../_lib/prepare.sh" \
  "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
