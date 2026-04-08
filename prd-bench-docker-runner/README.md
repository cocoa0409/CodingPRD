# prd-bench-docker-runner

Docker-based benchmark runner. Builds the model's implementation and the test suite into separate containers, connects them on an isolated Docker network, and collects structured test results.

## Install

```bash
pip install -e .
```

## Usage

### CLI

```bash
# Basic
prd-bench-docker-run \
  --task-dir ./my-task \
  --impl-dir ./my-task/workspace/implementation \
  --results-file results.json

# Full options
prd-bench-docker-run \
  --task-dir ./my-task \
  --impl-dir ./my-task/workspace/implementation \
  --port 8080 \
  --results-file results.json \
  --keep-containers \
  --log-level DEBUG
```

### Programmatic

```python
from prd_bench_docker_runner import DockerBenchmarkRunner, RunConfig

config = RunConfig(
    task_dir="./my-task",
    impl_dir="./my-task/workspace/implementation",
    results_file="results.json",
)
results = DockerBenchmarkRunner(config).run()
print(f"{results.passed}/{results.total} passed")
```

## What it does

```
prd-bench-docker-run --task-dir ... --impl-dir ...
        │
        ▼
┌─ Build implementation image ────────┐
│ docker build impl-dir/Dockerfile    │
├─────────────────────────────────────┤
│ Build test image                    │
│ (test_suite + test_helpers + deps)  │
├─────────────────────────────────────┤
│ Create isolated Docker network      │
│ Start implementation container      │
│ Poll until HTTP ready               │
├─────────────────────────────────────┤
│ Start test container on same network│
│ pytest → JUnit XML                  │
├─────────────────────────────────────┤
│ Collect results.xml from container  │
│ Cleanup (containers, network, imgs) │
└─────────────────────────────────────┘
        │
        ▼
   results.json
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--task-dir` | required | Task directory (contains `test_suite/`, `test_helpers/`, `Dockerfile.test`) |
| `--impl-dir` | required | Implementation directory (contains `Dockerfile` + source code) |
| `--port` | 10000 | Port the implementation listens on |
| `--build-timeout` | 300 | Docker image build timeout (seconds) |
| `--startup-timeout` | 60 | Implementation readiness timeout (seconds) |
| `--test-timeout` | 600 | Test execution timeout (seconds) |
| `--results-file` | — | Output JSON path |
| `--run-id` | auto | Unique prefix for Docker resource names (enables parallel runs) |
| `--keep-containers` | false | Retain containers after run for debugging |
| `--log-level` | INFO | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## Parallel Execution

Each run is isolated by `--run-id`. Run multiple evaluations concurrently:

```bash
prd-bench-docker-run --task-dir ./my-task --impl-dir output/model_a --run-id a --results-file a.json &
prd-bench-docker-run --task-dir ./my-task --impl-dir output/model_b --run-id b --results-file b.json &
wait
```

## Results Format

Same structured JSON as `prd-bench-local-runner`:

```json
{
  "total": 281,
  "passed": 281,
  "failed": 0,
  "errors": 0,
  "skipped": 0,
  "duration_seconds": 39.3,
  "tests": [...]
}
```
