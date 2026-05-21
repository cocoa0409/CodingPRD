# `harbor_tasks/_lib/` — shared Harbor task scaffolding

This directory holds the **reusable** pieces that every Harbor task in
`harbor_tasks/` consumes. Per-task directories should be as thin as possible.

## Layout

```
_lib/
├── prepare.sh                       # single-task hydrator: vendors shared + task assets
├── prepare-all.sh                   # bulk hydrator: iterate every tasks/task_*/
└── shared/
    ├── agent/
    │   └── instruction.md           # Harbor's launcher prompt (methodology),
    │                                  shared across every task
    ├── environment/
    │   └── Dockerfile               # base image used by every task
    ├── tests/
    │   ├── test.sh                  # thin wrapper around `prd-bench-local-run` CLI
    │   └── results_to_reward.py     # local-runner results.json → /logs/verifier/reward.json
    └── solution/
        └── solve.sh                 # oracle: copy reference impl into /app/implementation
```

## How a Harbor task uses `_lib/`

Nothing under `harbor_tasks/<task-name>/` is committed — the repo-root
`.gitignore` rule `harbor_tasks/task_*/` excludes the whole tree. The
two config files Harbor expects (`task.toml`, `README.md`) are written
from default templates in `_lib/prepare.sh` the first time you hydrate.

Adding a new task is purely a `tasks/<name>/` exercise. To use it through
Harbor, hydrate:

```bash
# single task — directory auto-created if missing
bash harbor_tasks/_lib/prepare.sh harbor_tasks/<task-name>/

# every tasks/task_*/ at once
bash harbor_tasks/_lib/prepare-all.sh
```

Subsequent runs are non-destructive for `task.toml` / `README.md` (so manual
timeout tweaks survive) and `rsync --delete` everything else from the
sources of truth.

The hydrator copies / vendors:

- `instruction.md`                    ← `_lib/shared/agent/instruction.md`
- `environment/Dockerfile`            ← `_lib/shared/environment/Dockerfile`
- `environment/INSTRUCTION.md`        ← source task `workspace/INSTRUCTION.md`
- `environment/PRD.md`                ← source task `workspace/PRD.md`
- `tests/test.sh`                     ← `_lib/shared/tests/test.sh`
- `tests/results_to_reward.py`        ← `_lib/shared/tests/results_to_reward.py`
- `tests/test_suite/`                 ← source task `test_suite/`
- `tests/test_helpers/`               ← source task `test_helpers/`
- `tests/prd-bench-local-runner/`     ← repo root `prd-bench-local-runner/`
- `solution/solve.sh`                 ← `_lib/shared/solution/solve.sh`
- `solution/implementation/`          ← source task `workspace/implementation/`

## The agent contract

Two distinct prompts reach the model:

1. **`instruction.md`** at task root → Harbor injects this as the agent's
   initial prompt. Generic, methodology-focused (planning, self-tests,
   modularisation, etc.). Points the agent at `/app/INSTRUCTION.md`.
2. **`/app/INSTRUCTION.md`** mounted in the container → the agent reads it
   itself. Task-specific engineering contract: required deliverables, port
   binding, startup script, etc.

Plus `/app/PRD.md` for the full API spec.

The agent works in `/app`, writes its solution into `/app/implementation/`,
and must produce:

- `/app/implementation/start.sh`  (installs deps + foregrounds an HTTP server on `$PORT`)
- `/app/implementation/...`       (source code)

The verifier then runs `bash start.sh` and pytest-tests the HTTP API.
