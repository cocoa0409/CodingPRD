# task_0001_food_delivery (Harbor)

Harbor wrapping of `tasks/task_0001_food_delivery_for_harbor`.

## Run

```bash
# 1. Hydrate (vendors shared + source assets into this directory)
./prepare.sh

# 2. Smoke-test with the oracle (uses the reference implementation)
harbor run -p harbor_tasks/task_0001_food_delivery -a oracle

# 3. Real run with claude-code
ANTHROPIC_API_KEY=... harbor run \
  -p harbor_tasks/task_0001_food_delivery \
  -a claude-code -m anthropic/claude-opus-4-7
```

## What you commit vs. what is hydrated

Committed (this directory):

```
prepare.sh
task.toml           # incl. [metadata].source_task — single source of truth
.gitignore
README.md
```

Hydrated by `prepare.sh` (gitignored):

```
instruction.md       # from harbor_tasks/_lib/shared/agent/ (Harbor launcher prompt)
environment/
  Dockerfile           # from harbor_tasks/_lib/shared/environment/
  INSTRUCTION.md       # from tasks/.../workspace/INSTRUCTION.md (engineering contract)
  PRD.md               # from tasks/.../workspace/PRD.md (API spec)
tests/
  test.sh                       # from harbor_tasks/_lib/shared/tests/
  results_to_reward.py          # from harbor_tasks/_lib/shared/tests/
  test_suite/                   # from tasks/.../test_suite/
  test_helpers/                 # from tasks/.../test_helpers/
  prd-bench-local-runner/       # from <repo>/prd-bench-local-runner/
solution/
  solve.sh                      # from harbor_tasks/_lib/shared/solution/
  implementation/               # from tasks/.../workspace/implementation/
```
