---
name: prd-bench-entrance
description: >
  Core orchestration entry point for the PRD benchmark pipeline. Given a scenario
  description, this skill drives the entire end-to-end flow: create task directory,
  generate scaffold YAML, generate PRD document, generate unit tests, generate
  Python/Flask implementation, run tests under `prd-bench-local-run --isolation
  per-test-server` (server restarts before every pytest test), and iterate until
  all tests pass. Use this skill whenever the user wants to create a new PRD
  benchmark task from a scenario, run the full benchmark pipeline, or says things
  like "create a new benchmark for X", "generate a full task from this scenario",
  "run the PRD bench pipeline", or "build a new task end to end".
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
Step 2: Subagent → prd-bench-scaffold-generator → SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml
    │
    ▼
Step 3: Copy INSTRUCTION.md (bash, no subagent)
    │
    ▼
Step 4: Subagent → prd-bench-doc-generator → PRD.md
        (reads SCAFFOLD.yaml only; BOTH SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml are withheld to prevent test-answer leakage into PRD)
    │
    ▼
    ┌───────────────────────────────────────────┬───────────────────────────────────────────┐
    ▼ (concurrent — single assistant message)   ▼
Step 5: Subagent → prd-bench-unit-test-generator  Step 6: Subagent → prd-bench-implementation-generator
        → test_helpers/ + test_suite/                    → implementation/ (incl. start.sh)
        (reads SCAFFOLD + DIFFICULTY + PRD)              (reads SCAFFOLD + PRD + INSTRUCTION)
    │                                           │
    └───────────────────────┬───────────────────┘
                            ▼
Step 7: One long-lived subagent owns the loop { prd-bench-local-run --isolation per-test-server → diagnose → fix → rerun → ... → PASS }
    │
    ▼
Step 8: Subagent → PRD finalizer → PRD_FINALIZED.md
        (reads PRD + implementation + tests; scaffold/worklog withheld; Step 7 diff inlined)
        (skipped if Step 7 had 0 implementation/ fixes)
    │
    ▼
Step 9: Subagent → PRD completeness scan → PRD_COMPLETED.md
        (full PRD-vs-implementation/ scan; reads PRD_FINALIZED.md if present else PRD.md;
         eliminates residual ambiguity + mismatch; always runs)
```

## Context Isolation Strategy

Each generation step (2, 4, 5, 6) runs as a **separate subagent** via the Agent tool. Step 7's iteration loop runs as a **single long-lived subagent** that retains context across its internal iterations (see Step 7 below for why). In both modes:

- A subagent starts with a **completely clean context** at spawn time — no accumulated history from prior steps or from the orchestrator
- The orchestrator passes only **file paths** to subagents, never file contents
- A subagent reads the skill instructions and input files fresh from disk at the start
- After a subagent finishes, its context is discarded — only the written files persist

This is critical because a scaffold YAML can be 1500+ lines, a PRD 300+ lines, test code thousands of lines — loading all of these into one context would crowd out the working memory needed for each step's actual task.

**How to spawn each subagent:**

```
Agent({
  description: "Step N: {brief description}",
  prompt: "{detailed instructions with file paths — see each step below}"
})
```

**Concurrency**: Steps 2 → 4 are strictly sequential (the PRD depends on the scaffold). Steps 5 and 6 have no mutual dependency — Step 5 reads SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml + PRD.md; Step 6 reads SCAFFOLD.yaml + PRD.md + INSTRUCTION.md — and they MUST be launched concurrently. Concurrency on Claude Code requires a **single assistant message with two Agent tool uses**; two Agent calls across separate messages run sequentially. Besides throughput, concurrent launch gives physical isolation: Step 6's impl-gen subagent cannot read `test_suite/` because the directory does not yet exist when it starts.

## Worklog

After every step completes (bash block or subagent), the orchestrator MUST append a record to `{task_dir}/worklog.md` before starting the next step. This is orchestrator-owned — write directly with the Write/Edit tool, no subagent. Use append; never overwrite earlier entries.

Format per entry:

```
## Step N: {short title} — {ISO-8601 UTC timestamp}

{verbatim summary returned by the subagent, OR a one-line note for bash-only steps}
```

For Steps 2, 4, 5, 6, 7 paste the subagent's returned summary **verbatim** — do not paraphrase or trim. The subagent's context is discarded on exit, so `worklog.md` is the only durable trace of what each generation step reported (coverage audits, design adjudications, fix history, deletion notes). For Steps 1 and 3 (bash-only) write one line stating what was created or copied. If Step 7 exits cleanly on the first sweep, its summary still goes in (the "0 iterations / 0 deletions / 0 fixes" record is itself meaningful evidence).

## Execution Steps

All paths below are relative to the project root (the directory containing `tasks/`, `skills/`, etc.).

### Step 1: Create Task Directory (bash, no subagent)

The task name follows the format `task_{NNNN}_{short_label}`:
- `NNNN` is a 4-digit zero-padded index
- `short_label` is a snake_case descriptor derived from the scenario (e.g., `e_commerce`, `hospital_shifts`)

To determine the index, scan `./tasks/` for existing directories matching `task_NNNN_*`, find the highest `NNNN`, and increment by 1. If no matching directories exist, start at `0001`.

Created directories must not have the same name as existing directories.

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
Read the skill at {project_root}/skills/prd-bench-scaffold-generator/SKILL.md to understand the full generation specification. Then generate the scaffold artifacts from the following scenario description and save them to {task_dir}/.

Scenario description (use verbatim, do not modify):
{scenario}

Output files (all three required):
- {task_dir}/SCAFFOLD.yaml                    (§1.0–§1.7; neither scaffold_difficulty_design nor scaffold_corner_design key)
- {task_dir}/SCAFFOLD_DIFFICULTY_DESIGN.yaml  (single top-level key scaffold_difficulty_design — §1.8)
- {task_dir}/SCAFFOLD_CORNER_DESIGN.yaml      (single top-level key scaffold_corner_design — §1.9)

Hard constraint — DO NOT look at any sibling task under {project_root}/tasks/ (no ls, glob, grep, or read of other task_*/ directories, their SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, PRD.md, tests, or implementation). Generate the scaffold purely from the scenario description above plus the scaffold-generator skill's own specification. Peeking at existing tasks biases the output toward prior designs and defeats the purpose of a fresh scaffold.
```

After the subagent completes, verify all three — `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and `SCAFFOLD_CORNER_DESIGN.yaml` — exist in `{task_dir}/`.

### Step 3: Copy Shared Files (bash, no subagent)

```bash
cp ./INSTRUCTION.md ./tasks/{task_name}/workspace/INSTRUCTION.md
```

### Step 4: Generate PRD (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-doc-generator/SKILL.md to understand the full generation specification. Then read the scaffold at {task_dir}/SCAFFOLD.yaml and generate a PRD document.

Input:  {task_dir}/SCAFFOLD.yaml
Output: {task_dir}/workspace/PRD.md

Hard constraint — DO NOT read EITHER `{task_dir}/SCAFFOLD_DIFFICULTY_DESIGN.yaml` OR `{task_dir}/SCAFFOLD_CORNER_DESIGN.yaml`. Both files are test-targeting indices (§1.8 depth, §1.9 breadth); they are deliberately withheld from PRD generation so their worked example numbers and `test_recipe` asserts cannot leak into the PRD prose the implementer will read. Do not open them, grep them, or reference their contents in any way.
```

### Step 5: Generate Unit Tests (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-unit-test-generator/SKILL.md to understand the full generation specification. Then read all four inputs:
- {task_dir}/SCAFFOLD.yaml                    (scaffold §1.1–§1.7)
- {task_dir}/SCAFFOLD_DIFFICULTY_DESIGN.yaml  (depth test index — §1.8; §2.1 queue A)
- {task_dir}/SCAFFOLD_CORNER_DESIGN.yaml      (breadth test index — §1.9; §2.1 queue B)
- {task_dir}/workspace/PRD.md                 (the contract under test)

Generate complete test infrastructure in {task_dir}/test_helpers/ and test cases in {task_dir}/test_suite/.

**Design-index-only contract.** The two design indices ARE the only test source. Every test you emit translates exactly one non-stub instance from §1.8 (queue A) or §1.9 (queue B); walking SCAFFOLD.yaml directly to invent baseline / smoke / RBAC / listing / pagination / common-field tests is forbidden. Every test's docstring MUST end with one line of the form:
  Design: Difficulty/<rule_id>/<instance.name>      (queue A)
  Design: Corner/<section>/<instance.name>          (queue B)
copied verbatim from the source yaml's `name:`. Untagged tests, dual-tagged tests, or tags pointing to non-existent instances are Stage 2 failures.

If an instance fails the PRD-first two-condition filter (no verbatim PRD coverage OR PRD does not uniquely-derive the asserted outcome), SKIP the instance — do not weaken, do not mark skip/xfail, do not emit a placeholder. Gaps stay gaps.
```

### Step 6: Generate Implementation (subagent)

Spawn a subagent with this prompt:

```
Read the skill at {project_root}/skills/prd-bench-implementation-generator/SKILL.md to understand the full generation specification. Then read these three files:
- {task_dir}/workspace/INSTRUCTION.md
- {task_dir}/SCAFFOLD.yaml
- {task_dir}/workspace/PRD.md

Generate a complete Python + Flask implementation in {task_dir}/workspace/implementation/ including a `start.sh` launcher. The implementation must boot cleanly from a fresh process on every invocation — the test harness uses `prd-bench-local-run --isolation per-test-server`, which kills and re-launches the server via `start.sh` before every individual pytest test.
```

### Step 7: Run Tests and Iterate

After Steps 5 and 6 complete, spawn **ONE long-lived fix subagent** that owns the entire iteration loop: it runs tests, reads results, diagnoses failures, fixes test or implementation code, reruns, and repeats — all in a single subagent conversation. The subagent, not the orchestrator, drives the loop.

**Why one long-lived subagent, not a fresh one per round:**
- Avoids re-reading 5000+ lines of context (PRD, SCAFFOLD, test_helpers, test_suite, implementation) on every iteration.
- Preserves the mental model of the domain (state machine, calculation rules, fixture shapes, role-to-resource mappings) across cycles.
- Preserves cross-iteration insights — "we already determined rule X is PRD-silent; similar cases in this round follow the same verdict."
- Anchoring on past wrong hypotheses is checked by the diagnostic protocol's STEP 0, which re-reads `results.json` fresh every iteration.

**Orchestrator's role**: spawn the subagent once, wait for it to exit. The subagent exits when `passed == total` and returns a summary.

**Subagent prompt:**

```
You are a PRD benchmark diagnostic expert. Your job is to iterate tests + fixes in {task_dir} until every test passes. You own the loop: run tests, read results, diagnose failures, fix, rerun, repeat.

Iteration step (you run this yourself each round): parallel 8-round stability sweep — all 8 rounds are launched concurrently in the background and joined with `wait`. There is no early-exit; every round runs to completion.

**Why 8 parallel rounds per iteration**: some implementation and test bugs are timing-sensitive (concurrency races whose server-side detection window closes before the racing request arrives; fixture ordering that happens to align on the first attempt; default-port collisions that only fire when another test is mid-flight). A single passing round can be a lucky round. The 8-round sweep surfaces flakiness in-iteration so a flaky bug cannot escape masquerading as a "fix". 

```bash
rm -f {task_dir}/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd {task_dir}/workspace/implementation && bash start.sh" \
    --test-dir       {task_dir}/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   {task_dir}/workspace/implementation/results.${i}.json &
done
wait
```

`--isolation per-test-server` restarts the server via `start.sh` before every pytest test, so per-test boot latency × test count drives each round's wall time. With 8 rounds running concurrently, total wall time stays ~1 × that figure but peak CPU/memory load is ~8×; plan the outer timeout for a single round, not the sum. Omit `--api-url`: the runner claims a free port per round via `~/.cache/prd-bench-local-runner/ports.tsv` (`fcntl.flock`) and exports it as `$PORT`, so the 8 concurrent runs (and any other pipelines on the same host) don't collide.

After `wait` returns, read all 8 `results.${i}.json` files (i = 1..8 — every round ran to completion).
- All 8 rounds have `passed == total` → **exit** with the Summary block at the end of this prompt.
- Otherwise → take the **union** of failing tests across all 8 rounds (a test that failed in round 3 but passed in round 1 still counts as a failure — that IS the flakiness signal), apply the diagnostic protocol below, fix, rerun the sweep. No iteration cap.

The benchmark's contract is: implementers read PRD.md only, never SCAFFOLD.yaml. Both layers of the test artifact must therefore trace to PRD prose:
  - `test_suite/` — the assertion must match a rule stated verbatim in PRD.
  - `test_helpers/` — the fixtures, factories, and role-header builders must construct preconditions and identities consistent with PRD (e.g., PRD's role-to-resource ownership model, PRD's declared payload shapes, PRD's declared entity statuses).

A test that asserts scaffold-only rules is unfair and must be deleted. A test whose fixture issues a request inconsistent with PRD (so the PRD-faithful implementation correctly rejects it) is a test bug — fix the fixture in `test_helpers/`, do not strip the PRD-required check from the implementation.

Diagnostic protocol — follow IN ORDER for each failing test:

STEP 0: READ FAILURE DETAIL

  Read every `results.${i}.json` from the most recent sweep (i = 1..8 — all 8 parallel rounds completed). For each test failing in ANY round, extract the failure detail (traceback, request URL/headers/payload, response body, tripped assertion) from the round(s) it failed in. Tests passing in some rounds but failing in others are flakiness and count as failures. Subsequent STEPs operate only on the union set identified here.

STEP 1: PRD COVERAGE + UNIQUE-DERIVABILITY CHECK

  This step has TWO sub-checks. Both must pass for the test to stay. A test that fails either one must be deleted — not weakened, not fixed against implementation, not skipped. Deletion is the benchmark's PRD-First contract.

  1a. COVERAGE — PRD mentions the rule.

      Read {task_dir}/test_suite/ and {task_dir}/test_helpers/ to understand what rule the failing test asserts (exact error_id, exact ordering, exact side-effect, exact formula, exact response-field presence/type).

      Grep {task_dir}/workspace/PRD.md for distinctive tokens from the test's assertions: the error_id, the field name, the threshold constant, the state name pair, the default value. Demand a verbatim quote — the rule must appear as a full sentence you can copy from PRD.md, not as a heading, not as a formula fragment, not as an enum member alone.

      Decide one of:
        - PRD VERBATIM-COVERS: proceed to 1b.
        - PRD IS SILENT: DELETE the test. Proceed to next failing test.

  1b. UNIQUE DERIVABILITY — the PRD sentence uniquely determines the assertion's expected outcome.

      Ask the two-reader question: could a faithful PRD-only implementer reasonably produce an implementation on which this test FAILS, while remaining consistent with the cited PRD sentence?

      Common collapse patterns — if ANY of these applies to the failing test, unique derivability is broken; DELETE the test:

        * COMPUTED-FIELD SILENCE: test asserts presence or value of a computed field, but PRD mentions the field only inside a formula (as an intermediate), never as a response-visible resource attribute. A reader could correctly omit the field from the serializer. (Example: `nights` on a reservation.)

        * DEFAULT-VALUE SILENCE: test asserts a concrete default for an optional input field, but PRD says only "optional" without naming the server-side default. A reader could correctly store `null`, omit the key, or default to a different boolean/enum. (Example: `yard_verified` on SCHEDULED home visits.)

        * BRANCH-ASYMMETRIC SIDE EFFECT: test asserts a side effect on one branch of a state transition (e.g., the FAIL branch), but PRD renders the happy-path branch fully while leaving the failing branch compressed to a single clause that omits this effect. (Example: FAIL submit writing `Adopter.home_visit_status = FAILED`.)

        * ERROR PRECEDENCE SILENCE: test asserts `ERR_A` on a race whose loser could, under a reasonable serialization, land in a state that earlier priority levels would report as `ERR_INVALID_STATE`. PRD names the target error but does not state that race semantics pre-empt the state-check path. Relax to `validate_error_is_one_of([ERR_A, ERR_INVALID_STATE])` if the PRD supports at least the "A is possible" reading; otherwise delete.

        * ENUM-MEMBERSHIP-ONLY: test demands a specific branch write a specific enum value, but PRD states only that the enum exists — no prose names the write pathway.

      If none of the above applies and a faithful PRD-only reader would arrive at the same outcome the test asserts, unique derivability holds — proceed to STEP 2.

      If uncertain, produce the verbatim PRD quote and the two alternate implementations it admits. If you can articulate both, the test fails unique derivability — DELETE.

  1c. PARTIAL COVERAGE HANDLING. When PRD covers part of the asserted rule but not the rest (e.g., names the error but not the priority; names the cascade entity but not the specific status write; names the race but not the pre-emption semantics), split the test: keep the covered assertion, remove the uncovered assertion. Never preserve an assertion whose rule is not verbatim in PRD.

STEP 2: TEST-vs-PRD CONSISTENCY CHECK (only if STEP 1 says PRD covers and uniquely determines the rule)

  Audit the test as a whole — not just the assertion, but the full test environment setup, the request actually issued, and the assertion that tripped. The test artifact spans TWO directories, and both are under audit here:
    - {task_dir}/test_suite/   (the test function and its assertions)
    - {task_dir}/test_helpers/ (fixtures, factories, per-role header builders, conftest, constants, assertion library)

  A fixture, factory, or role-header helper that constructs a precondition inconsistent with the PRD is a TEST BUG, not an implementation bug. Test_helpers counts as "the test" for the purpose of this check.

  a. Trace the failing test end-to-end. Using STEP 0's captured request/response and the source of the test function, list every helper the test (or its setup chain) invoked:
       - which fixture built the entities in play
       - which factory constructed the request payload
       - which header helper produced X-User-ID / X-User-Role
       - which assertion helper evaluated the response
     Every one of these is part of "the test's expressed logic".

  b. Cross-reference the test's expressed logic — setup + request + assertion together — against the PRD sentence STEP 1 pinned. Does the test express exactly the rule the PRD sentence requires, no more and no less? Check all of:

       * Setup state: do the entities created by fixtures satisfy the PRD preconditions for this flow (status, relationships, timestamps, counters, ownership chain)?
       * Request identity: does X-User-ID / X-User-Role / ownership id match the role-to-resource mapping the PRD requires? For example, if PRD requires "the acting restaurant must be the one that owns the order", does the test send a header whose user-id resolves to the order's restaurant_id — not a shared constant that would fail any ownership check regardless of implementation?
       * Request payload: field names, types, and required/optional shape match PRD verbatim?
       * Assertion: expected error_id, expected field name, expected boundary (inclusive vs exclusive), expected status transition match PRD verbatim?

     Decide one of:
       - TEST IS WRONG: the test's setup, request, or assertion does not faithfully express the PRD rule. Fix the offending artifact in whichever layer it lives:
           * Assertion mis-translates PRD wording → edit the test function in test_suite/.
           * Fixture / factory / role-header helper constructs a precondition that violates PRD (wrong ownership mapping, wrong entity status, missing required relationship, shared identity across owners PRD requires to be distinct, etc.) → edit the relevant file in test_helpers/.
           * Request payload is malformed relative to PRD → edit the factory (or the test function if the test constructs payload inline).
         The fix must make the test MORE faithful to PRD, never less. Never add skip / xfail. Never downgrade an exact error_id assertion to an HTTP-status assertion. If the fix in test_helpers/ affects many tests, that is fine — it means the fixture bug had wide reach.
       - TEST IS FAITHFUL: the setup, request, and assertion all faithfully express the PRD rule. Proceed to STEP 3.

STEP 3: IMPLEMENTATION FIX (only if PRD covers the rule, uniquely determines the behavior, AND the test — setup + request + assertion — is faithful to PRD)

  a. Read the relevant code in {task_dir}/workspace/implementation/ and fix the implementation so the test passes.
  b. Never remove or weaken an implementation check that PRD requires just because tests fail to exercise it correctly. If a PRD-required check (e.g., ownership, state gate, precondition) only looks "too strict" because the test setup cannot satisfy it, that belongs in STEP 2 (fix test_helpers), not here.

Cardinal rules:

- DELETE a test when STEP 1a finds PRD silent on the asserted rule.
- DELETE a test when STEP 1b finds PRD does not uniquely determine the asserted outcome (the two-reader experiment produces divergent implementations).
- Never delete a test because it is "strict", "brittle", or "hard to pass". The deletion criterion is PRD coverage + unique derivability, not difficulty.
- NEVER weaken an assertion to make implementation pass. Downgrading an `error_id` check to an HTTP-status check, replacing a boundary test with an approximate one, or adding `pytest.mark.skip` / `@pytest.mark.xfail` are all forbidden. (Exception: relaxing an exact-error assertion to `validate_error_is_one_of([...])` IS permitted when PRD only names a member of the set, not the specific choice — this is a coverage correction, not a hack.)
- NEVER remove or weaken an implementation check that PRD requires in order to accommodate a test fixture that violates the PRD precondition. If a PRD-required check (ownership, state gate, role scoping, referential integrity) rejects requests the tests issue, and the reason is that test_helpers constructed the request with a precondition PRD forbids (e.g., shared X-User-ID across distinct resource owners), the fixture is the bug — fix test_helpers in STEP 2, do not strip the check from the implementation.
- NEVER add an endpoint, response field, side effect, header, or capability to `implementation/` that does NOT trace to a verbatim PRD sentence, even if doing so makes failing tests pass.
- NEVER seed, preload, register, or hardcode any entity data in `implementation/` at startup. The implementation encodes the *system* (state machines, calculations, validations, endpoints); it never owns *data*. Every entity any test needs is constructed by the test (or its fixtures, acting as an API client) via declared endpoints. Storage MUST be in-memory only (Python dicts / maps keyed by id) — no SQLite file, no JSON dump on disk, no `/tmp` cache, no external persistence — so that `start.sh` re-invocation by the per-test-server isolation wipes every byte of state and guarantees a fresh boot. 
- TRIAGE HINT: when ≥5 failing tests share the same setup error (e.g., the same "Setup step failed" trace, the same 4xx from the same helper call), treat test_helpers as the first suspect before attributing to implementation. A common upstream fixture bug routinely masquerades as many independent implementation bugs.
- When in doubt about STEP 1, produce both: (i) the verbatim PRD quote that states the rule, and (ii) the two divergent PRD-faithful implementations that would and would not pass the test. If you cannot produce (i) or you CAN produce (ii), the test goes.
- Every deletion must be accompanied by a one-line note in the summary (see below) naming the test, the silence/collapse pattern, and the scaffold rule that drove the test's generation. These notes aggregate into feedback for doc-generator (Zero-Silence Rule violations) and for unit-test-generator (unique-derivability misses).
- After every batch of fixes, re-run the full 8-round parallel sweep above before making any further interpretation decisions. A fix only counts when all 8 parallel rounds pass.

Summary (emit when exiting after a clean 8-round parallel sweep):
- Iterations run.
- Tests deleted (with PRD-silence category per cardinal rule above).
- Fixes applied to `test_helpers/` (which file, which fixture/factory/assertion, one-line why).
- Fixes applied to `implementation/` (which file, which function, one-line why).
```

The orchestrator does not need to inspect failures itself — the subagent owns all of that, including the local-run invocation, the results parsing, and the decision whether to continue. The orchestrator just waits for the subagent to exit.

### Step 8: Finalize PRD — align documentation to implementation (subagent)

Step 7's revisions, deletions and assertion-weakenings mark the places where `PRD.md` does not uniquely determine a behavior the implementation has already chosen, or mismatch between current implementation and `PRD.md`. Step 8 patches those spots, producing `workspace/PRD_FINALIZED.md` — a MINIMAL diff over `PRD.md` based on `<step_7_diff>` such that a fresh implementer reading `PRD_FINALIZED.md` alone produces a code base behaviorally equivalent to `workspace/implementation/`.

**Skip condition.** If Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — i.e. zero iterations beyond the baseline — then `PRD.md` already determined every behavior the implementation exhibits, and Step 8 is skipped. Do not spawn the subagent in this case.

**Step 7 hand-off.** Before spawning, the orchestrator extracts the Step 7 entry from `worklog.md` (deletions, `test_suite/` fixes, `test_helpers/` fixes, `implementation/` fixes) and inlines it verbatim as `<step_7_diff>` in the prompt below. The diff is the focus list — the subagent uses it to target known PRD silences rather than scanning the whole document.

**Subagent prompt:**

```
Produce {task_dir}/workspace/PRD_FINALIZED.md — a minimal patch of {task_dir}/workspace/PRD.md that pins every place where the implementation makes a concrete behavioral choice that PRD does not uniquely determine or implementation used a different logic than the PRD. Goal: a fresh implementer reading PRD_FINALIZED.md alone produces a code base behaviorally equivalent to {task_dir}/workspace/implementation/.

**HARD SCOPE — read this before anything else: every PRD edit you make must trace to a specific fix which reveal PRD-silence or PRD-mismatch with current `implementation/` — `implementation/` fix, test deletions, `test_suite/`/`test_helpers/` fixes - listed in `<step_7_diff>`. Nothing else.**

**NO-NEW-MISMATCH RULE.** Step 8's edit **scope** is locally bounded to `<step_7_diff>` items, but Step 8's edit **perspective is global**. Each edit's wording must remain consistent with the entire current implementation, including paths Step 7 never exercised. Wording that accidentally narrows, redefines, reorders, or excludes behavior the implementation exhibits anywhere off the Step 7 site becomes a brand-new mismatch that Step 9 must undo.

Before committing each edit, you MUST enumerate every code path in `implementation/` logically related to the edit's subject — not just the Step 7 site, but every callsite, branch, helper, cascade, and parallel endpoint that touches the same field/entity/operation — and confirm your proposed wording is consistent with all of them. If any enumerated path would be mis-described, revise the wording (widen, soften, re-scope) before committing. The search is triggered by the edit itself, not by any keyword in it; every edit gets the search regardless of how innocuous it looks. When in doubt, prefer under-determined wording — a looser PRD is recoverable in Step 9; a false universal claim is indistinguishable from a genuine PRD/impl divergence.

You may read workspace: PRD.md, implementation/, test_helpers/, test_suite/, INSTRUCTION.md.
You MUST NOT read: SCAFFOLD*.yaml, worklog.md.

Implementation is the alignment target. Tests are NOT — Step 7 has already weakened or deleted assertions that PRD did not pin, so test_suite/ is sometimes laxer than implementation/. Treat test files only as auxiliary evidence of where Step 7 found PRD ambiguity or mismatch; align `PRD_FINALIZED.md` to what implementation/ actually does.

<step_7_diff>
{verbatim Step 7 worklog entry: deletions, test_suite fixes, test_helpers fixes, implementation fixes}
</step_7_diff>

Method:

0. `cp {task_dir}/workspace/PRD.md {task_dir}/workspace/PRD_FINALIZED.md`. Edit only PRD_FINALIZED.md.
1. For each <step_7_diff> item: locate the matching behavior in implementation/. Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open — not every item is a PRD silence (some are pure fixture bugs), or impl mismatch with PRD.md.
2. Where PRD already determines behavior, keep prose verbatim; elsewhere insert or revise inline to match impl, change as little as possible. No new sections. Never invent behavior the impl does not exhibit.
3. **Apply the NO-NEW-MISMATCH RULE before committing each edit, every time.** Identify the edit's subject; enumerate every impl path that touches that subject (not only the Step 7 site); confirm your proposed wording is consistent with all of them. If any enumerated path would be mis-described, revise — widen, soften, or re-scope the wording — before committing. The pre-edit search is mandatory regardless of how innocuous the wording looks; it is the edit itself, not any keyword in the edit, that triggers it.

Summary on exit:
- PRD.md vs PRD_FINALIZED.md line counts and %-delta.
- One bullet per change: `{PRD section} — {insert|revise} — {what changed} — {impl file:line}`.
- Per-edit pre-edit search log: for each edit, list (a) the subject identified, (b) the impl paths enumerated and read/grepped, (c) the wording adjustment made (if any) to keep all enumerated paths consistent with the new sentence. An empty (c) is fine — but (a) and (b) are mandatory for every edit, even ones that look obvious.
```

### Step 9: Complete PRD — eliminate residual ambiguity and mismatch (subagent)

**Purpose.** Step 8 only patches PRD at sites Step 7's fixes touched. Many PRD silences impl resolved at generation time — without ever producing a Step 7 failure signal because the test suite did not assert them, or because impl's chosen interpretation happened to align with what the test asserted — remain. Step 9 closes this gap with a full PRD-vs-`implementation/` scan, producing `workspace/PRD_COMPLETED.md` — a minimal patch such that every behavior in `implementation/` traces to a PRD sentence with no residual ambiguity or mismatch.

**Input.** Start from `workspace/PRD_FINALIZED.md` if Step 8 produced it; otherwise from `workspace/PRD.md`.

**No skip.** Step 9 always runs — the scan itself is the only way to confirm completeness.

**Subagent prompt:**

```
Produce {task_dir}/workspace/PRD_COMPLETED.md — a minimal patch over the latest PRD, such that wherever PRD prose admits multiple valid interpretations, it is revised to pin the one `implementation/` actually adopted. Goal: zero remaining PRD silence or mismatch versus implementation/.

You may read: PRD_FINALIZED.md (if present，otherwise PRD.md), implementation/, test_helpers/, test_suite/, INSTRUCTION.md.
You MUST NOT read: SCAFFOLD*.yaml, worklog.md.

Implementation is the alignment target. Tests are NOT — Step 7 has already weakened or deleted assertions that PRD did not pin; treat tests only as auxiliary cross-reference, never as authority.

Method:

0. If `{task_dir}/workspace/PRD_FINALIZED.md` exists, `cp PRD_FINALIZED.md PRD_COMPLETED.md`; otherwise `cp PRD.md PRD_COMPLETED.md`. Edit only PRD_COMPLETED.md.
1. Walk implementation/ exhaustively — every endpoint, state machine transition, calculation formula, validation rule, error response, default value, side effect, response field shape, ordering rule. For each impl behavior, locate the corresponding PRD passage and classify:
   - PRD already pins this behavior uniquely → no change.
   - PRD is silent (ambiguity) → insert minimal inline prose pinning what impl does.
   - PRD describes a different behavior (mismatch) → revise inline to match impl.
2. Change as little as possible: prefer in-paragraph inserts/revisions over new paragraphs; never add new sections; never invent behavior impl does not exhibit.

Summary on exit:
- Source file (PRD_FINALIZED.md or PRD.md) vs PRD_COMPLETED.md line counts and char-delta.
- Counts: ambiguity-pins, mismatch-revisions.
- One bullet per change: `{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`.
```

## Key Principles

1. **PRD.md is the contract; SCAFFOLD.yaml is the generator index.** Every implementation behavior must trace to PRD prose. Every test artifact — the assertion in `test_suite/` AND the fixture, factory, or role-header helper in `test_helpers/` that sets up the call — must trace to PRD prose. The scaffold exists to *drive generation* — it is not a contract the implementer can read. When test and scaffold agree but PRD is silent, **the PRD wins**: delete the test. When PRD and scaffold disagree on semantics (threshold boundaries, error names, state names), that is a bug in the doc-generator skill — report it rather than silently favoring one side, but if you must proceed, favor PRD.

2. **Unit test correctness is the first priority — and "the test" means BOTH `test_suite/` and `test_helpers/`.** Tests are the benchmark's measuring instrument. A test is the composition of three layers, all generated by the unit-test-generator and all subject to correctness audit:
   - **Setup/precondition** — fixtures, factories, per-role header builders, conftest scaffolding (in `test_helpers/`). Encodes the *state* and *identity* the request is issued from.
   - **Request** — the API call the test function issues, often routed through a client/factory helper.
   - **Assertion** — the expected status code, error_id, field presence, boundary, or state transition (in `test_suite/`).

   A bug in any of the three corrupts the measurement. A shared X-User-ID across distinct resource owners in `test_helpers/test_users.py` is just as much a test bug as an off-by-one in a boundary assertion — and can silently cascade into dozens of "implementation" failures that are actually fixture-induced. Before touching any implementation code, verify that every failing test's **setup, request, AND assertion** are all stated in or consistent with PRD prose. A test that passes by being lenient is worse than useless; a test whose fixture forces the implementation to drop a PRD-required check is actively harmful. Fixes to `test_helpers/` that ripple across many tests are normal and expected — the fixture bug's reach is the size of its ripple.

3. **Hacking tests is forbidden. Deleting PRD-uncovered or PRD-ambiguous tests is required. Repairing PRD-inconsistent fixtures is also required.** These look similar but are distinct:
   - **Forbidden (test hacking):** deleting a test because it's "too strict", changing an expected value to match current implementation output, downgrading an `error_id` check to a generic HTTP-status check, adding `@pytest.mark.skip`/`@pytest.mark.xfail` to dodge a failure, weakening a boundary test to an approximate one. **Also forbidden:** stripping a PRD-required check from the implementation because the current test fixtures can't satisfy it — that is implementation-hacking to fit a broken fixture.
   - **Forbidden (implementation hacking):** adding an endpoint, response field, side effect, header, or capability to `implementation/` that does NOT trace to a verbatim PRD sentence, even if doing so makes failing tests pass. **Equally forbidden: seeding, preloading, or hardcoding any entity data in `implementation/` at startup.** The implementation encodes the system; tests build all state via API calls. If tests depend on a server-side capability or seeded state PRD does not declare, the bug lives in `test_helpers/` (or upstream in the scaffold) — fix it there, never paper over with implementation back-doors.
   - **Required (PRD alignment — assertion level):** deleting a test whose asserted rule either (a) has no verbatim PRD coverage, or (b) has PRD coverage but PRD does not uniquely determine the asserted outcome — i.e., a faithful PRD-only implementer could produce a different but still-consistent implementation that the test would fail on. See Step 7's STEP 1a/1b.
   - **Required (PRD alignment — fixture/helper level):** editing `test_helpers/` when a fixture, factory, or role-header helper constructs a precondition inconsistent with PRD (e.g., shared X-User-ID across owners PRD requires to be distinct, wrong entity status before a transition, missing required relationship, payload shape that doesn't match PRD's declared schema). This is STEP 2 of the fix-cycle protocol. See Step 7's STEP 2.

   The distinguishing double question for every candidate **deletion**:
   - *"Can I produce a verbatim PRD quote that states the rule this test asserts?"* (coverage)
   - *"Does that quote pin the assertion's expected outcome to a single answer, such that every faithful PRD reader would arrive at it?"* (unique derivability)

   Both must be "yes" for the test to stay. Either "no" → the test goes.

   The distinguishing question for every candidate **fixture repair**:
   - *"Does the PRD require some property of the request (role, ownership id, entity state, payload shape) that the current fixture fails to supply?"* — if yes, the fixture is the bug; fix it in `test_helpers/`, and leave the implementation's PRD-required check intact.

4. **Scenario description passes through verbatim.** The user's input to this skill is forwarded unmodified to `prd-bench-scaffold-generator`. Do not summarize, restructure, or "improve" it.

5. **Implementation uses Python + Flask.** All generated implementations use the mandated Python + Flask stack with in-memory storage.

6. **Per-test-server isolation is required for testing.** Always use `prd-bench-local-run --isolation per-test-server` for the test/iterate loop. The harness kills and re-launches the API server (via `start.sh`) before every individual pytest test, so any test that passes only because of state left over by a previous test will surface as a real failure here — exactly the kind of bug the iteration loop needs to see and either fix in the implementation or correct in `test_helpers/`.

7. **Context isolation via subagents.** Each generation step runs in its own fresh subagent. The iteration loop (Step 7) runs in a **single long-lived** subagent that retains context across cycles — one sub-conversation that owns the run-diagnose-fix-rerun loop, rather than a fresh subagent per round (which would waste tokens re-reading the domain). The orchestrator stays lightweight — it only tracks file paths and pass/fail exits, never loads generated file contents into its own context.

## Output

When complete, the task directory will contain:

```
tasks/{task_name}/
├── SCAFFOLD.yaml                          # Structured specification (§1.1–§1.7)
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml        # Depth test index — §1.8 (withheld from PRD gen)
├── SCAFFOLD_CORNER_DESIGN.yaml            # Breadth test index — §1.9 (withheld from PRD gen)
├── worklog.md                             # Append-only per-step record (orchestrator-written summaries)
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
    ├── INSTRUCTION.md                     # Build contract (start.sh + PORT/0.0.0.0/foreground; evaluator runs `bash start.sh`)
    ├── PRD.md                             # Natural language requirements (input to Steps 5/6)
    ├── PRD_FINALIZED.md                   # Minimal patch of PRD.md at Step 7 `implementation/` fix sites (Step 8 output; absent if Step 8 skipped)
    ├── PRD_COMPLETED.md                # Minimal patch over PRD_FINALIZED.md (or PRD.md) eliminating residual ambiguity + mismatch via full impl scan (Step 9 output)
    └── implementation/                    # Working Python/Flask server
        ├── start.sh                       # Foreground launcher (reads $PORT, binds 0.0.0.0)
        ├── requirements.txt
        ├── app.py
        ├── ...
        └── results.{1..8}.json            # Per-round results from the final 8-round stability sweep (all passing)
```
