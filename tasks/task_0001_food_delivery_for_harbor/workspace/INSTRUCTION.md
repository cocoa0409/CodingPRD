# Implementation Instructions

You are building a REST API server based on the requirements in `PRD.md`.

## What You Must Produce

Place all files in the `./implementation/` directory:

1. **`start.sh`** at `./implementation/start.sh` — a single shell script that:
   - Installs all dependencies your implementation needs
   - Starts your HTTP server in the foreground (the script must not exit while the server is running)
2. **Implementation source code** in `./implementation/` — no language restriction, use any language and framework you prefer

## Startup Requirements

Your `start.sh` must:

- Listen on the port specified by the `PORT` environment variable (default: 10000)
- Bind to `0.0.0.0` (not `127.0.0.1`)
- Respond to HTTP requests within 60 seconds of `start.sh` being invoked
- Keep the server running in the foreground (use `exec` for the final server command, or do not background it)

## How the Evaluator Will Run Your Code

The evaluator will execute, from `./implementation/`:

```bash
bash start.sh
```

That is the entire contract. No Dockerfile, no other entrypoint is consulted.

## Examples

Python / Flask:

```bash
#!/bin/bash
set -e
pip install -q -r requirements.txt
exec python app.py
```

Node.js / Express:

```bash
#!/bin/bash
set -e
npm install --silent
exec node server.js
```

All API requirements are defined in `PRD.md`. Read it carefully and implement accordingly.
