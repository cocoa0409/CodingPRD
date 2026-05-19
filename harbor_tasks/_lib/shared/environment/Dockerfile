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

WORKDIR /app

# Bring every file from environment/ (e.g. INSTRUCTION.md, PRD.md) into /app so
# the agent can read them. The .dockerignore excludes this Dockerfile itself.
COPY . /app/
