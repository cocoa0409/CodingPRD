FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Tools the agent and tests may need:
#   curl/ca-certificates/git : general
#   nodejs/npm               : required by Harbor's claude-code agent installer
#   build-essential          : if impl deps need to compile native extensions
#   procps/net-tools/lsof    : process / port introspection
#   psmisc                   : `fuser -k <port>/tcp` for the verifier's final
#                              port cleanup (prd-bench-local-runner's kill_port
#                              prefers lsof, falls back to fuser; without these
#                              installed kill_port becomes a silent no-op, an
#                              orphaned server can hold pipes open, and the
#                              trial hangs)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git nodejs npm build-essential \
        procps net-tools lsof psmisc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Pre-install Claude Code via npm. Harbor's claude-code agent normally bootstraps
# via `curl -fsSL https://claude.ai/install.sh | bash`, but Cloudflare blocks
# that endpoint from this container's egress IP (403 challenge). The npm package
# goes through registry.npmjs.org, which is not gated. We still need to satisfy
# Harbor's install step, so we shim `curl` below to no-op the claude.ai URL.
RUN npm install -g @anthropic-ai/claude-code \
 && command -v claude >/dev/null

# Shim curl so Harbor's hardcoded `curl ... claude.ai/install.sh | bash` exits 0
# (claude is already installed). Other curl usage is unaffected — we exec the
# real binary for any URL that isn't the claude.ai installer.
RUN mv /usr/bin/curl /usr/bin/curl.real \
 && printf '%s\n' \
    '#!/bin/bash' \
    'for arg in "$@"; do' \
    '  case "$arg" in' \
    '    *claude.ai/install.sh*|*downloads.claude.ai/claude-code-releases/bootstrap.sh*)' \
    '      echo ": claude-code pre-installed in image, skipping bootstrap"' \
    '      exit 0' \
    '      ;;' \
    '  esac' \
    'done' \
    'exec /usr/bin/curl.real "$@"' \
    > /usr/bin/curl \
 && chmod +x /usr/bin/curl

WORKDIR /app

# Bring every file from environment/ (e.g. INSTRUCTION.md, PRD.md) into /app so
# the agent can read them. The .dockerignore excludes this Dockerfile itself.
COPY . /app/
