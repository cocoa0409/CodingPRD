# prd-bench-runner

Generic benchmark runner for API compliance testing. Manages the full test lifecycle: server startup, health monitoring, pytest execution, crash recovery, graceful shutdown, and structured result collection.

## Install

```bash
pip install -e .
```

## Usage

### CLI

```bash
# Basic: start server + run tests + stop server
prd-bench-run \
  --start-command "cd my-impl && python app.py" \
  --test-dir ./test_suite

# Full options
prd-bench-run \
  --start-command "cd my-impl && python app.py" \
  --test-dir ./test_suite \
  --api-url http://localhost:8080 \
  --timeout 60 \
  --test-timeout 10 \
  --results-file results.json

# Server already running externally
prd-bench-run --test-dir ./test_suite --skip-lifecycle
```

### Programmatic

```python
from prd_bench_runner import BenchmarkRunner

runner = BenchmarkRunner(
    start_command="cd my-impl && python app.py",
    test_dir="./test_suite",
    api_url="http://localhost:3000",
)
results = runner.run()
print(f"{results.passed}/{results.total} passed")
```

## What it does

```
prd-bench-run --start-command "..." --test-dir ./test_suite
        │
        ▼
┌─ Kill port ──────────────────────────┐
│ Spawn server subprocess              │
│ Poll GET until HTTP response (30s)   │
├──────────────────────────────────────┤
│ Run pytest on test_suite/            │
│   ├─ Before each test: liveness check│
│   ├─ If server crashed: auto-restart │
│   └─ Collect JUnit XML results       │
├──────────────────────────────────────┤
│ SIGTERM server → SIGKILL fallback    │
│ Kill port (safety net)               │
└──────────────────────────────────────┘
        │
        ▼
   results.json (structured)
```

## Testing Utilities (`prd_bench_runner.testing`)

The `testing` subpackage provides reusable infrastructure for writing API compliance tests:

```python
from prd_bench_runner.testing import (
    GenericApiClient,          # Base HTTP client — subclass and add endpoint methods
    validate_success,          # Validate success response envelope → returns data
    validate_error,            # Validate error envelope + cross-check HTTP status
    validate_paginated,        # Validate paginated list response → (data, meta)
    get_success_data,          # Lenient validator for test setup steps (any 2xx)
    is_valid_uuid,             # UUID format check
    is_iso8601_timestamp,      # ISO 8601 timestamp check
    assert_cost_precision,     # Monetary decimal precision assertion
    assert_version_incremented,# OCC version monotonicity assertion
    assert_race_outcome,       # Validate concurrent operation results
    assert_exactly_one_succeeds,
    run_race,                  # Execute operations concurrently
    build_user_headers,        # Construct role-based auth headers
    set_error_http_status_map, # Register error_id → HTTP status mapping
    NON_EXISTENT_UUID,         # Standard non-existent UUID for 404 tests
)
```

## Results Format

```json
{
  "total": 42,
  "passed": 38,
  "failed": 3,
  "errors": 1,
  "skipped": 0,
  "duration_seconds": 87.3,
  "tests": [
    {
      "name": "test_create_order_valid",
      "file": "test_suite/test_01_crud.py",
      "status": "passed",
      "duration_seconds": 0.45,
      "error_message": null
    }
  ]
}
```

## Server Requirements

The runner is language-agnostic. The server under test just needs to:

1. Be startable via a shell command (e.g., `python app.py`, `go run .`, `cargo run`)
2. Listen on a configurable HTTP port
3. Handle `SIGTERM` for graceful shutdown

The `--start-command` supports `cd dir && command` syntax to set the working directory.
