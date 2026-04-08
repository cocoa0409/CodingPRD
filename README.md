# CodingPRD

A benchmark suite for evaluating LLM capabilities on system-level, repository-scale software engineering. Given only a PRD and implementation instructions, the model must architect and implement a complete production-grade service from scratch. Correctness is measured by black-box end-to-end test suites that interact exclusively through the service interface.

## Repository Layout

```
CodingPRD/
├── tasks/
│   └── {task_name}/
│       ├── workspace/
│       │   ├── INSTRUCTION.md          # Implementation constraints and Dockerfile spec (model input)
│       │   ├── PRD.md                  # Complete API specification (model input)
│       │   └── implementation/         # Reference implementation (ground truth, withheld from model)
│       ├── test_helpers/               # Per-task test infrastructure (API client, factories, assertions)
│       ├── test_suite/                 # pytest-based end-to-end test cases
│       └── Dockerfile.test             # Containerized test harness
├── prd-bench-docker-runner/            # Containerized evaluation pipeline
└── prd-bench-local-runner/             # Subprocess-based runner for local development
```

## Evaluation Pipeline

1. Model is provided `workspace/INSTRUCTION.md` and `workspace/PRD.md` as sole inputs
2. Model generates application source code and a `Dockerfile` under `workspace/implementation/`
3. `prd-bench-docker-runner` orchestrates the evaluation:
   - Builds the model-generated implementation into a Docker image
   - Builds the task's test suite into a separate image
   - Creates an isolated Docker network and runs both containers
   - Executes pytest against the implementation's HTTP endpoints
   - Collects structured results as `results.json`

```bash
# Containerized evaluation
prd-bench-docker-run \
  --task-dir tasks/{task_name} \
  --impl-dir tasks/{task_name}/workspace/implementation \
  --results-file results.json

# Local evaluation
prd-bench-local-run \
  --start-command "cd tasks/{task_name}/workspace/implementation && uv run app.py" \
  --test-dir tasks/{task_name}/test_suite \
  --results-file results.json
```

## Task Structure

Each directory under `tasks/` constitutes an independent benchmark instance:

| Path | Role | Model Visibility |
|------|------|:---:|
| `workspace/INSTRUCTION.md` | Specifies Dockerfile conventions, port binding, output directory | Exposed |
| `workspace/PRD.md` | Full service specification: endpoints, schemas, business logic, error catalog | Exposed |
| `workspace/implementation-ground_truth/` | Reference implementation (ground truth) | Withheld |
| `test_helpers/` | API client, payload factories, response validators, fixtures | Withheld |
| `test_suite/` | pytest test modules | Withheld |
| `Dockerfile.test` | Test container definition | Withheld |

All tests are black-box: validation is performed exclusively through HTTP request/response pairs.

## Test Runners

| Runner | Use Case | Mechanism |
|--------|----------|-----------|
| `prd-bench-docker-runner` | Batch evaluation, language-agnostic scoring | Docker build + network isolation |
| `prd-bench-local-runner` | Development, debugging, rapid iteration | Subprocess lifecycle + local pytest |
