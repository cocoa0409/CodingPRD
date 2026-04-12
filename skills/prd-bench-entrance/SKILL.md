---
name: prd-bench-entrance
description: >
  Core orchestration entry point for the PRD benchmark pipeline. Given a scenario
  description, this skill drives the entire end-to-end flow: create task directory,
  generate scaffold YAML, generate PRD document, generate unit tests, generate
  Python/Flask implementation, run Docker-based tests, and iterate until all tests
  pass. Use this skill whenever the user wants to create a new PRD benchmark task
  from a scenario, run the full benchmark pipeline, or says things like "create a
  new benchmark for X", "generate a full task from this scenario", "run the PRD
  bench pipeline", or "build a new task end to end".
---

# PRD Benchmark Entrance — End-to-End Pipeline Orchestrator

This skill orchestrates the full PRD benchmark pipeline from a scenario description to a passing implementation. Each heavy-lifting step runs in its own **subagent** so that context stays clean and isolated — the orchestrator (you) only tracks file paths and pass/fail status, never loads the full content of generated files into your own context.

## Input

A **scenario description** — a natural-language description of the system to build. This description is passed **verbatim, unmodified** to `prd-bench-scaffold-generator` as its input. Do not summarize, rewrite, restructure, or add to it — pass the user's exact text through.

## Pipeline Overview

```
Scenario Description
    │
    ▼
Step 1: Create task directory (bash, no subagent)
    │
    ▼
Step 2: Subagent → prd-bench-scaffold-generator → SCAFFOLD.yaml
    │
    ▼
Step 3: Copy Dockerfile.test + INSTRUCTION.md (bash, no subagent)
    │
    ▼
Step 4: Subagent → prd-bench-doc-generator → PRD.md
    │
    ▼
Step 5: Subagent → prd-bench-unit-test-generator → test_helpers/ + test_suite/
    │
    ▼
Step 6: Subagent → prd-bench-implementation-generator → implementation/
    │
    ▼
Step 7: Loop { bash: docker test → Subagent: diagnose & fix → repeat }
```

## Context Isolation Strategy

Each generation step (2, 4, 5, 6) and each fix iteration (7) runs as a **separate subagent** via the Agent tool. This means:

- Each subagent starts with a **completely clean context** — no accumulated history from prior steps
- The orchestrator passes only **file paths** to subagents, never file contents
- Each subagent reads the skill instructions and input files fresh from disk
- After a subagent finishes, its context is discarded — only the written files persist

This is critical because a scaffold YAML can be 1500+ lines, a PRD 300+ lines, test code thousands of lines — loading all of these into one context would crowd out the working memory needed for each step's actual task.

**How to spawn each subagent:**

```
Agent({
  description: "Step N: {brief description}",
  prompt: "{detailed instructions with file paths — see each step below}"
})
```

Do NOT use `run_in_background` — steps are sequential (each depends on the prior step's output files).

## Execution Steps

All paths below are relative to the project root (the directory containing `tasks/`, `skills/`, `prd-bench-docker-runner/`, etc.).

### Step 1: Create Task Directory (bash, no subagent)

The task name follows the format `task_{NNNN}_{short_label}`:
- `NNNN` is a 4-digit zero-padded index
- `short_label` is a snake_case descriptor derived from the scenario (e.g., `e_commerce`, `hospital_shifts`)

To determine the index, scan `./tasks/` for existing directories matching `task_NNNN_*`, find the highest `NNNN`, and increment by 1. If no matching directories exist, start at `0001`.

```bash
max_index=$(ls -d ./tasks/task_[0-9][0-9][0-9][0-9]_* 2>/dev/null | \
  sed 's/.*task_\([0-9]*\)_.*/\1/' | sort -n | tail -1)
next_index=$(printf "%04d" $(( ${max_index:-0} + 1 )))
task_name="task_${next_index}_{short_label}"
mkdir -p ./tasks/${task_name}/workspace
```

### Step 2: Generate Scaffold (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-scaffold-generator/SKILL.md to understand
the full generation specification. Then generate a complete SCAFFOLD.yaml from the following
scenario description and save it to {task_dir}/SCAFFOLD.yaml.

Scenario description (use verbatim, do not modify):
{scenario}

Output file: {task_dir}/SCAFFOLD.yaml
```

After the subagent completes, verify `SCAFFOLD.yaml` exists.

### Step 3: Copy Shared Files (bash, no subagent)

```bash
cp ./Dockerfile.test ./tasks/{task_name}/Dockerfile.test
cp ./INSTRUCTION.md ./tasks/{task_name}/workspace/INSTRUCTION.md
```

### Step 4: Generate PRD (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-doc-generator/SKILL.md to understand
the full generation specification. Then read the scaffold at {task_dir}/SCAFFOLD.yaml
and generate a PRD document.

Input: {task_dir}/SCAFFOLD.yaml
Output: {task_dir}/workspace/PRD.md
```

### Step 5: Generate Unit Tests (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-unit-test-generator/SKILL.md to understand
the full generation specification. Then read both:
- {task_dir}/SCAFFOLD.yaml
- {task_dir}/workspace/PRD.md

Generate complete test infrastructure in {task_dir}/test_helpers/ and test cases in
{task_dir}/test_suite/. Tests must rigorously align with every rule in the SCAFFOLD
and PRD — exact error_ids, exact field names, exact state transitions, exact calculation
formulas with correct precision.
```

### Step 6: Generate Implementation (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-implementation-generator/SKILL.md to
understand the full generation specification. Then read these three files:
- {task_dir}/workspace/INSTRUCTION.md
- {task_dir}/SCAFFOLD.yaml
- {task_dir}/workspace/PRD.md

Generate a complete Python + Flask implementation in {task_dir}/workspace/implementation/
including a Dockerfile.
```

### Step 7: Run Tests and Iterate

This is the most critical step. The orchestrator runs Docker tests via bash, then spawns a **fresh subagent** for each fix cycle.

#### 7.1 Run Tests (bash, no subagent)

```bash
prd-bench-docker-run \
  --task-dir ./tasks/{task_name} \
  --impl-dir ./tasks/{task_name}/workspace/implementation \
  --results-file ./tasks/{task_name}/workspace/implementation/results.json
```

#### 7.2 Check Results (orchestrator reads results.json directly)

Read `results.json` and extract `passed`, `total`, `failed`. If `passed == total`, the pipeline is complete.

#### 7.3 Fix Cycle (subagent, fresh context each round)

If tests fail, spawn a **new subagent** for the fix. Each fix subagent gets a clean context — it doesn't carry baggage from previous fix attempts.

Subagent prompt:

```
You are a PRD benchmark diagnostic expert. {passed}/{total} tests pass, {failed} fail.

Failed tests: {list of failed test names from results.json}

Diagnostic protocol:

1. Read {task_dir}/workspace/implementation/results.json for full failure details
2. For each failing test, read the test source in {task_dir}/test_suite/ and {task_dir}/test_helpers/
3. Cross-reference every assertion against {task_dir}/SCAFFOLD.yaml and {task_dir}/workspace/PRD.md
4. If a test contradicts the SCAFFOLD or PRD → fix the test to match the spec exactly
5. If the test is correct → read the relevant code in {task_dir}/workspace/implementation/ and fix it

Cardinal rules:
- NEVER weaken, delete, skip, or xfail a test to make the implementation pass
- Test fixes must make the test MORE faithful to the spec, never less
- Verify test correctness FIRST, fix implementation SECOND
```

#### 7.4 Iteration Loop

```
loop:
    run prd-bench-docker-run (bash)
    read results.json
    if passed == total: break
    spawn fix subagent (fresh context)
```

Each iteration is a fresh subagent, so context never accumulates across fix cycles. Keep going until all tests pass — no iteration limit.

## Key Principles

1. **SCAFFOLD.yaml and PRD.md are the sole source of truth.** Every test assertion and every implementation behavior must trace back to a specific entry in these two files. When in doubt, re-read the spec.

2. **Unit test correctness is the first priority.** Tests are the benchmark's measuring instrument — if the instrument is wrong, the measurement is meaningless. Before touching any implementation code, verify that every failing test faithfully represents the spec. A test suite that passes by being lenient is worse than useless.

3. **Never hack tests to make implementation pass.** Specifically, never:
   - Delete a test because it's "too strict"
   - Change an expected value to match what the implementation currently returns
   - Weaken an assertion (e.g., checking only HTTP status instead of error_id)
   - Skip an edge case or boundary test
   - Add `pytest.mark.skip` or `@pytest.mark.xfail` to dodge failures
   
   If a test fails and the test is correct per the spec, the implementation must change — not the test.

4. **Scenario description passes through verbatim.** The user's input to this skill is forwarded unmodified to `prd-bench-scaffold-generator`. Do not summarize, restructure, or "improve" it.

5. **Implementation uses Python + Flask.** All generated implementations use the mandated Python + Flask stack with in-memory storage.

6. **Docker isolation is required for testing.** Always use `prd-bench-docker-run` (not the local runner) for the test/iterate loop, because it mirrors the real evaluation environment.

7. **Context isolation via subagents.** Every generation step and every fix iteration runs in its own subagent. The orchestrator stays lightweight — it only tracks file paths and pass/fail counts, never loads generated file contents into its own context.

## Output

When complete, the task directory will contain:

```
tasks/{task_name}/
├── SCAFFOLD.yaml                          # Structured specification
├── Dockerfile.test                        # Test container definition
├── test_helpers/                          # Test infrastructure
│   ├── __init__.py
│   ├── types.py
│   ├── api_client.py
│   ├── api_errors.py
│   ├── assertions.py
│   ├── factories.py
│   ├── constants.py
│   ├── test_users.py
│   └── fixtures.py
├── test_suite/                            # Pytest test files
│   ├── conftest.py
│   └── test_*.py
└── workspace/
    ├── INSTRUCTION.md                     # Build constraints
    ├── PRD.md                             # Natural language requirements
    └── implementation/                    # Working Python/Flask server
        ├── Dockerfile
        ├── requirements.txt
        ├── app.py
        ├── ...
        └── results.json                   # Test results (all passing)
```
