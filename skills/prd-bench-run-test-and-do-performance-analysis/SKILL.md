---
name: prd-bench-run-test-and-do-performance-analysis
description: |
  Run tests against a PRD benchmark implementation under per-test-server isolation and produce a concise
  root-cause analysis. Given a workspace directory that contains `implementation/`, this skill executes
  `prd-bench-local-run --isolation per-test-server` (which restarts the API server via `start.sh` before
  every pytest test), collects `results.json`, cross-references failures against the test helpers
  (factories, assertions, fixtures) and the PRD, then writes `PERFORMANCE_ANA.md` into the workspace.
  Each invocation auto-allocates its own free TCP port via the runner's file-locked port registry, so
  multiple instances of this skill can run concurrently on the same host against different workspaces
  without port collisions.

  Trigger when: the user asks to "test and analyze", "run tests and diagnose", "evaluate an implementation",
  "generate performance analysis", or provides a workspace path and wants to know why tests fail.
  Also trigger when the user mentions "prd-bench" + "analysis" or "diagnosis".
---

# PRD Bench: Run Tests & Performance Analysis

You receive a **workspace directory** as input. It sits under a task directory with this layout:

```
tasks/<task_name>/
├── workspace/                  # or workspace-<variant>/
│   ├── INSTRUCTION.md
│   ├── PRD.md                  # the spec the model was given (source of truth)
│   └── implementation/         # the code under test (must contain start.sh)
├── test_helpers/               # factories, assertions, fixtures, constants
└── test_suite/                 # pytest modules
```

The workspace path the user gives you is the `workspace/` (or `workspace-<variant>/`) directory.

## Step 1: Run Tests

Derive the **task directory** (parent of the workspace) and run:

```bash
prd-bench-local-run \
  --start-command "cd <workspace>/implementation && bash start.sh" \
  --test-dir       <task_dir>/test_suite \
  --isolation      per-test-server \
  --timeout        60 \
  --test-timeout   10 \
  --results-file   <workspace>/results.json \
  --log-level      INFO
```

The `--isolation per-test-server` flag kills and re-launches the server (via `start.sh`) before every individual pytest test, so the implementation must boot cleanly from a fresh process — there is no carry-over state between tests, and any failure that depends on shared state is a real bug, not a fixture artifact.

**Do not pass `--api-url`.** With it omitted, the runner asks the OS for a free ephemeral port, claims it in a file-locked registry (`~/.cache/prd-bench-local-runner/ports.tsv`, serialized via `fcntl.flock`), and exports that port as the `PORT` environment variable that `start.sh` sees. Multiple concurrent `prd-bench-local-run` invocations on the same host therefore coexist without colliding on a single fixed port. Pin a port via `--api-url` only when external tooling needs to know it up front — and accept that doing so re-introduces the collision risk this skill's concurrency story depends on.

Use a 10-minute outer timeout for the whole command (per-test-server restarts add startup latency multiplied by test count — at ~3-5s startup × 100+ tests, expect several minutes of pure boot time). If startup or tests fail catastrophically (exit before producing `results.json`), report the startup error and stop.

## Step 2: Collect Evidence

Read these in parallel — you need all of them to do a proper analysis:

1. `<workspace>/results.json` — the full test report (every test name, status, error message)
2. `<task_dir>/test_helpers/factories.py` — what field names and payloads the tests actually send
3. `<task_dir>/test_helpers/assertions.py` — what field names and types the tests assert on responses
4. `<task_dir>/test_helpers/fixtures.py` — composite setup helpers that chain entity creation (shows the dependency graph)
5. `<workspace>/PRD.md` — the natural-language spec the model was given (the contract)
6. `<workspace>/implementation/` — the source code (read the main app file)

**Visibility model**: The model under evaluation only saw PRD.md (and INSTRUCTION.md). The test suite was built from the same PRD. SCAFFOLD.yaml exists but is invisible to both the model and the analysis — do NOT reference it. The PRD is the single source of truth for what the implementation should do.

## Step 3: Analyze — Methodology

The goal is: **from symptoms to root causes to model weaknesses**. Follow this method:

### 3a. Cluster failures by error signature

Group all failed tests by their `error_message` pattern. Typical clusters:

- **Setup failures** (`"Setup step failed with HTTP 4xx: ..."`) — the test couldn't even build its prerequisite data. These cascade: one broken entity blocks all downstream tests that depend on it.
- **Assertion failures** (`"assert X is Y"`, `"Expected N, got M"`) — the test reached the endpoint but got wrong data back.
- **Status code mismatches** (`"Expected 201, got 400"`) — request was rejected unexpectedly.

Count each cluster. The largest cluster is almost always the dominant root cause.

### 3b. Pinpoint contract violations

For each failure cluster, triangulate across three sources:

- **Test sends** (factories.py) vs. **implementation requires** (request validation in source code)
- **Test asserts** (assertions.py) vs. **implementation returns** (response construction in source code)
- **PRD specifies** (prose, examples, field names) vs. **implementation uses**

Don't enumerate a taxonomy of violation types — just describe what you actually find. Each task and each implementation will break differently; let the evidence speak.

### 3c. Map the dependency graph

Identify which entities are **prerequisite** for others. In most PRD-bench tasks, there's a critical path:

```
Entity A (create) → Entity B (depends on A) → Workflow C (depends on B) → ...
```

A contract violation at a root entity cascades through every downstream test. Quantify: "Entity X failure accounts for N/M total failures (P%)."

### 3d. Identify model weaknesses

Distill the root causes into **generalizable model behavior patterns**. Ask: what cognitive or reasoning failure led the model to produce this specific bug? Name the pattern, describe it in one or two sentences, and explain why it matters in a black-box test regime. Let the evidence drive the diagnosis — every task will surface different weaknesses.

### 3e. Note what passed

Briefly characterize what DID pass — it reveals which parts of the implementation are correct and scopes the problem. Passing tests usually cover code paths that don't depend on the broken entity.

## Step 4: Write PERFORMANCE_ANA.md

Write `<workspace>/PERFORMANCE_ANA.md`. The report must be:

- **English**
- **Concise** — no filler, no excessive tables, no restating what's obvious
- **Structured as: symptom → root cause → model weakness**

Use this skeleton:

```markdown
# Performance Analysis: <workspace_name>

**Result: P/T (X%)**

## Root Causes

### 1. <dominant issue> — N failures (P%)

One paragraph: what the implementation does wrong, what the contract says, why it cascades.

### 2. <next issue> — masked by #1 / N additional failures

Brief description. Use a compact table if there are multiple field-level mismatches.

(repeat as needed, usually 2-4 root causes)

## Model Weaknesses

**<Pattern name>.** One or two sentences describing the behavior pattern and why it fails in a black-box test regime.

(repeat for each identified weakness, usually 2-4)

## What Passed

One paragraph characterizing the passing tests and what they imply about the implementation's correctness.
```

Keep the total report under 60 lines. Every sentence should carry information. No "In this section we will discuss..." prose.

## Important

- Do NOT modify any code. This is a read-only analysis.
- Do NOT suggest fixes. The report is diagnostic, not prescriptive.
- Focus on the **interface contract** (field names, types, presence) as the primary failure vector — logic errors are secondary in PRD-bench.
- When a single root cause dominates (>80% of failures), say so plainly and don't over-elaborate the minor causes.
