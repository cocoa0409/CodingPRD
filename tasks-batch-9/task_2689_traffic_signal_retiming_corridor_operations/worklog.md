## Step 1: Create task directory — 2026-09-04T06:57:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2689_traffic_signal_retiming_corridor_operations and its workspace/ subdirectory. Index 2689 pre-assigned by the orchestrating caller; no scan of ./tasks/ performed.

## Step 2: Generate scaffold — 2026-09-04T08:59:30.000Z

All three artifacts are complete, parse as YAML, and the linter is clean.

**`scaffold_lint.py` output (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2689_traffic_signal_retiming_corridor_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2689_traffic_signal_retiming_corridor_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2689_traffic_signal_retiming_corridor_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1326

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_2689_traffic_signal_retiming_corridor_operations/`

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2892 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2472 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5458 |

**SCAFFOLD.yaml (§1.0–§1.7)** — `api_prefix: /signal-ops`; 14 entities, 7 state machines, 2 §1.2.1 OCC concurrency rules, 12 calculations, 35 validation rules (priority ladder 1→85), 60 endpoints, 66 error codes, 6 roles. Archetypes: `temporal_windowing` / `compliance_audit`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`; `role_model: segregation_of_duties`; `consistency_model: immediate`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key, 9 rules / 20 instances: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key, all 9 guide sections, 82 instances (58 full recipes + 24 `excluded_because` stubs pointing at the §1.8 instance that already owns the corner): entities 12, state_machines 17 (6 stubs), calculations 14 (5), validations 14 (7), endpoints 8 (3), errors 6, rbac 4, cross_cutting_complexity_layers 6 (3), consistency_model 1. All 102 instance names across both design files are unique.

Fixes applied while reaching clean lint: 28 list-endpoint pagination captures changed from `$.data.total_count` to `$.total_count` (the linter models `data` as the array for `Entity[]` outputs); 3 hardcoded `expected_*_version: 1` literals removed from role-denial payloads (priority 10 rejects before the OCC gate reads the body); wrong enum/field names corrected against §1.5 (`triage` takes `disposition: TRIAGE|NO_ACTION` with `note?`, not `severity`/`ACCEPT`; `POST /corridors/{id}/members` returns `CorridorMember`, so the capture is `sequence_index`).

## Step 3: Copy shared files — 2026-09-04T08:59:40.000Z

Copied ./INSTRUCTION.md to tasks/task_2689_traffic_signal_retiming_corridor_operations/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T09:21:00.000Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md` — **493 lines**, written incrementally (one `Write` + heredoc appends), never in a single large call.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Nested Retrieval and Path Resolution · 2.7 Validation Precedence · 2.8 Precision, Rounding and Units · 2.9 Optimistic Concurrency on Parent Aggregates · 2.10 Operational Posture: The Gate on Signal Work · 2.11 Cascade Discipline · 2.12 Conserved Quantities and Compensation
- §3 Business Logic & Workflows: 3.1 The Signal Inventory · 3.2 Corridor Assembly, Screening and Program Selection · 3.3 Citizen Feedback: Requesters, Complaints and the Bucket Partition · 3.4 Opening a Retiming Project and Completing the Before Study · 3.5 Plan Development: Drafting Timing Plans and Phase Splits · 3.6 The Corridor Coordination Pipeline · 3.7 Pedestrian Timing Compliance and Waivers · 3.8 Certification, Return and Field Implementation · 3.9 Transit and Emergency Vehicle Priority · 3.10 Fine Tuning, Performance Measurement and Project Disposition
- §4 Endpoint Definitions
- §5 Error Code Catalogue

**Verified tail:** ends at `| \`ERR_CLOCK_NOT_MONOTONIC\` | 422 |` — a completed final section, no mid-sentence truncation. Orchestrator independently re-verified with `tail -12` and section grep.

**Hard Contract results (machine-checked against SCAFFOLD.yaml)**
- **Contract 1 — Field-Name Coverage: PASS.** All 123 declared field names appear verbatim in backticks; 0 missing. All 88 enum values and state-machine states also appear in backticks in §1–§3.
- **Contract 2 — Rule Coverage: PASS.** All 38 transitions across all 7 state machines are stated as explicit FROM → TO pairs with guards, side effects and cascade ordering. All 35 validations appear as a 35-rung ordered ladder in §2.7 in exact scaffold priority order. Both concurrency rules in §2.9. All 12 calculations in prose, including both dual-variant pairs.
- **Contract 3 — §3 Path Purity: PASS.**

**Coverage confirmations**
- §1.5 endpoints: all **60** present in §4, paths/methods exact, no extras; authorized-role sets match scaffold exactly.
- §1.4 error codes: all **66** in §5 with matching HTTP statuses; all 66 also named in §1–§3 prose.
- §2.2 byte-identical to the canonical response-structure section.

**Scaffold contradictions resolved:** segregation of duties scoped to certify/waive/approve only; `ERR_PED_CLEARANCE_INSUFFICIENT` status taken from `errors[]` (422); `ERR_PRIORITY_BUDGET_EXHAUSTED` applies to both TSP and EVP; coordinate-with-no-drafts → invalid request; field-tuning COMPLETE with unresolved observations → `ERR_OBSERVATIONS_UNRESOLVED`.

Neither design yaml was opened; no sibling task directory accessed.

## Step 6: Generate implementation — 2026-09-04T10:00:00.000Z

(Launched concurrently with Step 5; completed first, so it is recorded first. Step 5's entry follows below.)

Implementation is complete, compiled, and validated by two independent end-to-end smoke suites (both `FAILURES: 0`). The smoke server on port 18689 was stopped by PID and the port is released; no pattern kills were used.

## Deliverable
`workspace/implementation/`

| Module | Lines | Module | Lines |
|---|---|---|---|
| `app.py` | 89 | `routes/__init__.py` | 1 |
| `errors.py` | 107 | `routes/intersections.py` | 202 |
| `clock.py` | 72 | `routes/corridors.py` | 175 |
| `db.py` | 75 | `routes/citizens.py` | 152 |
| `response.py` | 55 | `routes/projects.py` | 452 |
| `auth.py` | 84 | `routes/plans.py` | 297 |
| `validators.py` | 201 | `routes/priority.py` | 118 |
| `calc.py` | 299 | `routes/observations.py` | 119 |
| `derive.py` | 254 | `routes/clock_admin.py` | 23 |
| `serializers.py` | 234 | `start.sh` | 12 |
| `cascades.py` | 214 | `requirements.txt` | 1 |
| `lookups.py` | 80 | **total** | **3316** |

## Endpoints: 60
intersections 10, corridors 9, citizens 8, projects 15, plans 10, priority 4, observations 3, clock 1 — verified by `grep -c "@bp.route"`.

## start.sh
Reads `$PORT` (default 8000), `app.py` does `app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)`, and `exec` keeps it in the foreground so the harness can kill/relaunch per test. `pip install` is guarded so 8 concurrent rounds don't contend. Storage is module-level Python dicts in `db.py`, reset on every boot; `clock.reset()` in `create_app()` re-pins the logical clock to `2026-08-01T00:00:00Z`. No SQLite, no file I/O, no seed data.

## Validation
Smoke suite 1 (happy path, ~40 requests): screening score 91.25 -> programming 35.00; Webster cycle 60 with cfr 0.6667; coordinated cycle overwrite 90 -> 60 with `drafted_cycle_length_sec` preserved; offsets 0 / 30 (1320 ft / 44 fps); split rescale 30/60 -> 20/40; ped check PASS at `required_ped_clear_sec` 10.0; implementation cascade (plan age 0, deployed cycle 60, budget 12); priority waterfall EVP 10 / TSP 2, then suspend -> EVP 0 / TSP 8; provisional metrics 310.0 / 250.0 / 19.35 / 32.5 vs certified weighted after-mean 255.0; close -> CLOSED then `ERR_PROJECT_TERMINAL`.

Smoke suite 2 (compensation and negative paths): re-draft supersede (old plan v2, SUPERSEDED, splits frozen); `ERR_CYCLE_EXCEEDS_LOCAL_MAX`, `ERR_DUPLICATE_TOD_PLAN`, `ERR_DUPLICATE_PHASE_NUMBER`, `ERR_SEQUENCE_INDEX_GAP`, `ERR_DUPLICATE_CORRIDOR_MEMBER`, `ERR_APS_STANDARD_MISMATCH`, `ERR_OVERSATURATED_APPROACH` at exactly cfr 0.95, `ERR_BEFORE_STUDY_INCOMPLETE`, `ERR_OBSERVATION_OUT_OF_WINDOW`, `ERR_COMPLAINT_INVALID_STATE`, `ERR_PLAN_COVERAGE_INCOMPLETE`; failing ped check (`PED_CLEAR_SHORT`, required 17.2) blocking submit, waiver by a non-author bubbling the plan to `WAIVED`, self-waiver refused with `ERR_SEGREGATION_OF_DUTIES`; return compensation (DRAFT, cycle restored to 90, offset 0, splits back to 30/60, checks deleted, `return_count` 1); posture `BLOCKED` removing an intersection from coverage; fine-tuning cascade (deployed plan -> DRAFT, project -> PLAN_DEVELOPMENT, `tuning_round` 1, provisional evaluation -> INVALIDATED); abandonment superseding plans and requeueing the linked complaint to OPEN with `reopen_count` 1 and `linked_project_id` cleared.

Two smoke-run expectations were wrong and were corrected in the throwaway script, not the server: `aog_pct_after` is 32.5 (130 on-green / 400 arrivals), and a 1700-veh count is cfr 0.9444 — below the 0.95 rejection threshold. One PRD detail flagged by the generator: only the *selected* count per intersection (greatest `count_date`, then `created_at`) feeds the coordination pipeline and its oversaturation gate, which the implementation follows.

Isolation held: nothing under `test_suite/`, `test_helpers/`, the two SCAFFOLD design YAMLs, or any sibling task directory was read; all writes confined to `workspace/implementation/`.

## Step 5: Generate unit tests — 2026-09-04T11:12:00.000Z

(Launched concurrently with Step 6 in the same assistant message batch order; finished after it.)

The suite is complete. Both design queues are fully translated.

## Files written (task root — nothing under `workspace/`)

**`test_helpers/`** (Stage 1, 2173 lines): `__init__.py` 38, `api_client.py` 349, `api_errors.py` 145, `assertions.py` 271, `constants.py` 64, `factories.py` 171, `fixtures.py` 672, `test_users.py` 58, `types.py` 445.

**`test_suite/`** (Stage 2, 6224 lines): `conftest.py` 60, `test_01_corridor_screening_and_selection.py` 313, `test_02_coordination_pipeline_arithmetic.py` 306, `test_03_plan_lifecycle_and_compensation.py` 277, `test_04_implementation_and_fine_tuning_cascades.py` 284, `test_05_priority_and_performance.py` 308, `test_06_complaints_and_temporal_rules.py` 381, `test_07_entity_shapes_and_defaults.py` 482, `test_08_state_machine_transitions.py` 629, `test_09_derived_calculations.py` 530, `test_10_validation_gates.py` 513, `test_11_endpoint_behaviours.py` 481, `test_12_error_catalogue.py` 697, `test_13_rbac_and_scoping.py` 558, `test_14_optimistic_concurrency.py` 365.

## Coverage

- **Total tests: 104.**
- **Queue A (Difficulty / §1.8): 46 tests across 20 of 20 non-stub instances** — every instance carries >=2 tests.
- **Queue B (Corner / §1.9): 58 tests across 58 of 58 non-stub instances** — 1:1. Per section: entities 12/12, state_machines 11/11, calculations 9/9, validations 7/7, endpoints 5/5, errors 6/6, rbac 4/4, cross_cutting_complexity_layers 3/3, consistency_model 1/1.
- **Instances SKIPPED for PRD-silence or non-unique derivability: none.** Every non-stub instance in both indices passed the two-condition filter. (The 24 `excluded_because:` stubs in the corner index were out of scope by construction.)

## Verification

- `python3 -m compileall test_helpers test_suite` -> clean.
- Citation/tag auditor (verbatim PRD fragment check + exactly one `Design:` line per test): **0 problems**.
- Tag-vs-yaml cross-check: **0 bad tags**; 104 tags = 46 queue-A + 58 distinct queue-B.
- Unused-import AST check: clean. No occurrence of the word "scaffold" anywhere in generated code.

## Design/PRD conflicts resolved (design asserted something the PRD contradicts)

- `category: "SIGNAL_TIMING"` (rbac instance 3) is not a PRD category — §3.3 declares `COORDINATION`, `PEDESTRIAN`, `DETECTION`, `TIMING_OTHER`. Used `COORDINATION`/`PEDESTRIAN`.
- `finding_code: "EARLY_RETURN"` and `"SPILLBACK"` — §3.10 declares `EARLY_RETURN_TO_GREEN` and `QUEUE_SPILLBACK`. Corrected.
- Hard-coded operator ids (`cert-1`, `eng-1`) replaced with the helpers' `AUTHOR_ID` / `REVIEWER_ID` constants, since the assertion is identity equality, not a literal.

Two precedence subtleties verified against §2.7 rather than assumed: the role gate (rung 3) pre-empts path 404s (rung 6), which validates the 32-call empty-database matrix probe; and the body-FK gate (rung 7) pre-empts the OCC gate (rung 11), which validates the two `ERR_*_NOT_FOUND`-with-stale-token cases in `test_14`.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root; no `test_*` files or directories were left under `workspace/`.


## Step 7: Iterate tests + fixes to green — 2026-09-04

Three iterations, each an 8-round parallel stability sweep under `setsid nohup`
(`--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`), diagnosed only
from the per-round `results.$i.json` files.

- **Iteration 1** — 91/104 in all 8 rounds; 13 deterministic failures, zero flakiness.
- **Iteration 2** — 103/104 in all 8 rounds; 1 residual failure (same root cause as a
  cluster already fixed, in a set comparison the first pass missed).
- **Iteration 3** — **104/104 in all 8 rounds.** Round wall time ~192 s each.

All 13 failures were test-artifact defects. **No change was made to
`workspace/implementation/` and no test was deleted or weakened.**

### Root causes and fixes

1. **Clock-stamped / client-supplied instant rendering (8 tests).** The suite asserted
   exact string equality against no-millisecond literals (`"2026-08-01T00:00:00Z"`) for
   `last_retimed_at`, `screened_at`, `received_at`, `recorded_at`,
   `last_tuning_completed_at` and a run's `started_at`. PRD §2.2/§2.4 fix a
   three-fractional-digit rendering only for `api_request_timestamp`, `created_at` and
   `updated_at`; for the §2.5 clock-stamped fields the PRD states only the *value* the
   field takes ("takes the logical clock's current value") and never the digit count,
   and it says nothing at all about whether a client-supplied instant is echoed verbatim
   or normalised. The exact rendering is therefore not uniquely derivable, while the
   *instant* is. Added `assert_instant_equals()` to `test_helpers/assertions.py` (parses
   both sides to a normalised instant tuple) and converted the 17 affected sites in
   `test_04`, `test_06`, `test_07`, `test_08`, `test_09`. The PRD-stated rule is kept;
   only the PRD-silent rendering detail is dropped.

2. **`ERR_TOD_WINDOW_OVERLAP` in a shared setup (2 tests, `test_02`).** The setup drafts
   plans A `[360, 540)` and B `[500, 700)` on the same intersection and then runs the
   coordination pipeline, leaving both `COORDINATED`. PRD §3.8 compares a submission
   against every other plan on the same `intersection_id` whose status is `COORDINATED`,
   `SUBMITTED`, `CERTIFIED` **or** `DEPLOYED`, so A and B mutually block and the tests'
   `submit_plan(A)` prelude could never succeed. Dropped the prelude: the overlap test
   now reads A's coordinated cycle/offset instead of submitting it and still asserts
   B's refusal; the adjacency test exercises only the D/E pair on the other intersection,
   which is the pair the rule is about.

3. **`NameError: record_run` (`test_07`).** `record_run` was used but absent from the
   `test_helpers.fixtures` import list. Added.

4. **`ERR_UNAUTHENTICATED` instead of `ERR_COMPLAINT_INVALID_STATE` (`test_08`).**
   `ApiClient.reopen_complaint` takes `(complaint_id, headers, payload=None)` — matching
   `resolve_complaint` — but the call site passed the payload as the headers argument, so
   the request went out with no role headers and tripped precedence rung 1. Swapped the
   two arguments at the call site.

5. **`study_window_days must be >= 30` (`test_10`).** The boundary test opened its
   projects with `study_window_days: 10`, which PRD §3.4 constrains to 30–730 inclusive,
   so the setup was refused at precedence rung 8 long before the freshness rule. Moved to
   the minimum legal 30 days and shifted the boundary instants to match
   (2026-08-01 + 30 d = 2026-08-31T00:00:00Z expired, 2026-08-30T23:59:59Z accepted).
## Step 7: Run tests and iterate — 2026-09-04T11:22:11.000Z

Clean sweep achieved. Summary:

## Iterations run: 3

- **Iteration 1** — 91/104 in all 8 rounds; 13 deterministic failures (zero flakiness — identical failure set every round).
- **Iteration 2** — 103/104 in all 8 rounds; 1 residual (same root cause as an already-fixed cluster, in a set comparison the first pass missed).
- **Iteration 3** — **104/104 in all 8 rounds**, ~192 s per round.

## Tests deleted: none

Every failing test's asserted rule was verbatim-covered by PRD and uniquely derivable; all 13 failures were defects in the test artifact itself.

## Fixes applied to `test_helpers/`

- `test_helpers/assertions.py` — added `assert_instant_equals()` (+ private `_instant()` normaliser). PRD §2.2/§2.4 fix a three-fractional-digit rendering only for `api_request_timestamp`, `created_at` and `updated_at`. For the §2.5 clock-stamped fields (`last_retimed_at`, `screened_at`, `received_at`, `recorded_at`, `last_tuning_completed_at`) the PRD states only the *value* ("takes the logical clock's current value") and never the digit count, and it is entirely silent on whether a client-supplied instant such as a run's `started_at` is echoed verbatim or normalised. Exact-string assertions against no-millisecond literals were therefore not uniquely derivable; instant equality is. Converted 17 sites across `test_04`, `test_06`, `test_07`, `test_08`, `test_09`. The PRD-stated rule is preserved; only the PRD-silent rendering is dropped.

## Fixes applied to `test_suite/`

- `test_02_coordination_pipeline_arithmetic.py`, both TOD-window tests — the shared setup leaves plans A `[360, 540)` and B `[500, 700)` on one intersection both `COORDINATED`. PRD §3.8 includes `COORDINATED` in the statuses a submission is compared against, so A and B mutually block and the `submit_plan(A)` prelude was unsatisfiable. Dropped the prelude (the overlap test now reads A's coordinated cycle/offset rather than submitting it); the adjacency test exercises only the D/E pair on the other intersection.
- `test_07_entity_shapes_and_defaults.py` — added the missing `record_run` import (`NameError`).
- `test_08_state_machine_transitions.py` — `api_client.reopen_complaint` has signature `(complaint_id, headers, payload=None)`; the call site passed the payload as headers, so the request went out headerless and tripped precedence rung 1 (`ERR_UNAUTHENTICATED`). Swapped the arguments.
- `test_10_validation_gates.py` — the study-window boundary test used `study_window_days: 10`, which PRD §3.4 constrains to 30–730 inclusive, so setup died at rung 8 before the freshness rule. Moved to 30 days and shifted the boundary instants to match (`2026-08-31T00:00:00Z` expired, `2026-08-30T23:59:59Z` accepted).

## Fixes applied to `implementation/`: none

The implementation was verbatim-faithful on every one of the 13 failures — notably the `LIVE_WINDOW_STATUSES` overlap set, the `study_window_days` 30–730 range gate, and the uniform three-fractional-digit timestamp rendering. No implementation check was removed or weakened, no assertion was downgraded to an HTTP-status check, and no skip/xfail was added.

**Orchestrator independent verification** (not the subagent's claim): all 8 `workspace/implementation/results.{1..8}.json` exist, were written 3 minutes before this entry, and each reports `total: 104, passed: 104, failed: 0, errors: 0, skipped: 0`; round 1 `duration_seconds: 191.95`. The clean-sweep claim is confirmed against the artifacts.

Step 8 is NOT skipped: Step 7 ran 3 iterations with 1 `test_helpers/` fix and 4 `test_suite/` fixes, so the skip condition (zero fixes of every kind) does not hold.

## Step 8: Finalize PRD — 2026-09-04T11:35:00.000Z

`PRD_FINALIZED.md` is written. Exactly one Step 7 item traced to a PRD silence; the other four were fixture-only defects.

## Line counts
- `PRD.md`: 493 lines -> `PRD_FINALIZED.md`: 495 lines (+2 lines, +0.41%). One inserted paragraph plus its blank separator; zero lines revised or deleted.

## Changes
- **§2.4 Common Resource Properties** — *insert* — pins that **every** instant-valued field the service emits (not just `created_at`/`updated_at`/`api_request_timestamp`) renders as ISO 8601 UTC with exactly three fractional digits and a `Z`, and that client-supplied instants are echoed **normalised**, not verbatim: non-`Z` offsets converted to UTC, absent fraction rendered `.000`, sub-millisecond precision discarded, unset nullable instants `null` — `implementation/clock.py:34-40` (`fmt`), `implementation/clock.py:43-68` (`parse`), `implementation/serializers.py:9,11,27,47,80,91,94,106,120,125,209`, `implementation/response.py:20`, `implementation/routes/clock_admin.py:23`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- **(a) Subject identified:** the serialisation format of every instant-valued field in a response payload — server-stamped, derived, *and* client-supplied.
- **(b) Impl paths enumerated (read/grepped):**
  - `grep -rn "isoformat\|strftime\|\.fmt(" --include=*.py` over all of `implementation/` — established that `clock.fmt` is the **single** renderer for every instant the API emits; no second code path, no per-field variation, no place that passes a raw string through.
  - `clock.py:34-40` `fmt()`: `astimezone(utc)` then `%03d` on `microsecond // 1000` with a literal `Z`. Truncation, not rounding; `fmt(None) -> None`.
  - `clock.py:43-68` `parse()`: accepts 1–9 fractional digits (truncated to 6 us), accepts `Z`/`z`/`+-HH:MM`/`+-HHMM`/absent offset, subtracts the offset to reach UTC.
  - `serializers.py` — all 13 serializer functions read; `_common` plus every domain instant: `last_retimed_at`, `screened_at`, `received_at`, `study_window_start_at`, `last_tuning_completed_at`, `count_date`, `started_at`, `recorded_at`, `observed_at`. The four client-supplied ones all go through `fmt` — the previously PRD-silent case.
  - `response.py:17-21` `_meta()` renders `api_request_timestamp` through the same `fmt`.
  - `routes/clock_admin.py:23` — the off-prefix clock endpoint's `current_utc` also uses `fmt`.
  - `validators.py:122-134` `req_ts`/`opt_ts` parse body instants into `datetime` objects before storage, so no request string is persisted verbatim to be echoed later.
  - Nullable-instant callsites (`serializers.py:27,47,94`) reach `fmt(None)` and render `null`.
- **(c) Wording adjustments made:** three. (1) Scoped the claim to "every instant-valued field **the service emits**" rather than a closed list, so the clock endpoint's `current_utc` and unexercised read paths stay inside the statement. (2) Wrote "precision finer than a millisecond is **discarded**" rather than "rounded", because `fmt` truncates via `microsecond // 1000` — "rounded" would have been a fresh mismatch. (3) Added the "nullable instant renders as `null`" clause after finding the three `row.get` callsites.

## Items that correctly received no PRD edit
- `test_02` TOD-window prelude — `routes/plans.py:22` `LIVE_WINDOW_STATUSES = ("COORDINATED","SUBMITTED","CERTIFIED","DEPLOYED")` matches §3.8 verbatim; the test's own setup was unsatisfiable.
- `test_07` missing `record_run` import, `test_08` swapped `reopen_complaint` positional args — pure fixture defects with no behavioural surface.
- `test_10` `study_window_days: 10` — `routes/projects.py:36` gates `30..730`, exactly as §3.4 already states.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk (`90a91,92`) inserting the §2.4 rendering paragraph plus a blank line — a real, non-empty, minimal patch.

## Step 9: Complete PRD — 2026-09-04T12:20:00.000Z

Run as **four sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2–4 edited in place). Partitioning by implementation module rather than one monolithic scan, so no pass had to hold all 3316 impl lines plus a 495-line PRD at once. Every pass was instructed not to revert, duplicate or contradict earlier passes' edits, and each verified earlier passes' sentinel strings still present on exit.

**Cumulative size:** `PRD_FINALIZED.md` 495 lines / 105,711 chars -> `PRD_COMPLETED.md` 495 lines / 129,566 chars (+23,855 chars). All edits in-paragraph; no new sections, no new paragraphs, no line-count change.

**Totals: 50 ambiguity-pins, 11 mismatch-revisions (61 edits).**

### Pass 1 — cross-cutting infra (app, errors, response, clock, db, auth, validators, lookups): 11 pins, 2 mismatches
- §1 — revise — mismatch — added the unauthenticated `GET /health` probe returning bare `{"status": "ok"}` outside the envelope; the clock endpoint was not the only prefix exception — `app.py:77-79`
- §2.1 — insert — ambiguity — identity headers whitespace-trimmed before any check (whitespace-only = absent), trimmed `X-User-ID` is what is recorded/compared, `X-User-ID` presence checked before `X-User-Role`, role matching exact/case-sensitive — `auth.py:37-48`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty chars from `A`–`Z`/`0`–`9` — `response.py:10-14`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, so responses served without a clock move share one timestamp — `response.py:20`
- §2.3 — insert — ambiguity — `limit`/`offset` parsed as decimal integers tolerating whitespace and explicit sign; empty/fractional/non-digit is `ERR_INVALID_PAGINATION` rather than defaulting — `validators.py:147-173`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order (applies to every `created_at ascending` ordering incl. §2.11 cascades); filter semantics raw-text case-sensitive, conjunctive, out-of-set value matches nothing, undeclared params ignored — `db.py:9-12,73-75`, `lookups.py:69-74`
- §2.4 — revise — ambiguity — `id` is a random UUIDv4 in canonical lower-case hyphenated form — `db.py:49-50`
- §2.4 — insert — ambiguity — inbound instant grammar (mandatory seconds, `T`/space, 1–9 fractional digits, optional `Z`/offset, omitted offset = UTC); date-only/second-less/non-string/impossible dates are `ERR_INVALID_REQUEST` — `clock.py:15-68`
- §2.5 — revise — ambiguity — `to_iso8601` required, parsed by the §2.4 grammar; success is 200 with `data` = `{"current_utc": ...}` — `routes/clock_admin.py:19-24`
- §2.6 — insert — ambiguity — two-FK bodies resolve in fixed order (`project_id` before `intersection_id`; `requester_id` before `corridor_id`); absent/null/non-string FK is a 422 raised before any FK resolution, beating a sibling's 404 — `validators.py:137-144`
- §2.7 rung 8 — insert — ambiguity — lenient body parsing (Content-Type ignored, absent/empty/unparseable body = `{}`, non-object JSON 422), zero coercion, JSON `null` treated as absent key so optionals take defaults, strings stored verbatim with bounds on the raw value — `validators.py:11-119`
- §2.9 — insert — ambiguity — OCC tokens must be non-negative JSON integers; malformed values 422 at rung 8 before any version comparison — `routes/plans.py:42`, `routes/priority.py:30`, `routes/projects.py:231`
- §5 — revise — mismatch — table was claimed exhaustive; pinned routing-level `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 decided before authentication, plus trailing-slash insignificance — `app.py:41,56-64`
- Deliberately not pinned: `ERR_INTERNAL`/500 and generic `ERR_HTTP_<code>` fallbacks (unreachable by well-formed requests); `auth.segregation`'s no-op on a null author id (unreachable).

### Pass 2 — calc / derive / serializers / cascades: 16 pins, 3 mismatches
- §2.4 — revise — mismatch — "nothing mutates a count after creation" was false; the pipeline recomputes a count's two derived numbers, refreshing no `updated_at`/`version` — `routes/projects.py:313-316`
- §3.2 — insert — ambiguity — `member_count` + four bucket counters live-derived per read; `avg_plan_age_days`, `complaint_count_12mo`, `priority_score`, `priority_score_variant` stored, rewritten only by screen / selection-decision / implementation cascade — `serializers.py:36-50`, `derive.py:108,116-123`
- §3.2 — insert — ambiguity — the age component divides the stored 2-decimal `avg_plan_age_days`, not the unrounded mean — `calc.py:92-93`
- §3.4 — revise — ambiguity — Webster's denominator uses the exact unrounded critical-flow-ratio quotient, never the persisted 4dp value — `calc.py:116-121`
- §3.6 — insert — ambiguity — count-selector final tie-break: the later-stored count wins — `calc.py:127-139`
- §3.6 — insert — mismatch — the chosen count's `critical_flow_ratio_sum`/`recommended_cycle_sec` are recomputed at pipeline time against the intersection's current `max_cycle_length_sec` and written back — `calc.py:116-124`
- §3.6 — insert — ambiguity — a plan with no phase splits is skipped (both totals 0, no residual, no coordinated phase); the §2.12 invariant binds only plans with >=1 split — `calc.py:149-153`
- §3.6 — insert — ambiguity — a MASTER plan whose intersection is not a corridor member gets `offset_sec` 0 — `calc.py:165-170`
- §3.7 — insert — ambiguity — a fresh check emits `waived_by_user_id`/`waiver_justification` as `null` — `serializers.py:181-183`
- §3.7 — insert — ambiguity — all seven numeric check fields are decimals, so a whole-second provided phase length emits `32.0` while the phase split emits `32` — `calc.py:183-209`
- §3.8 — insert — ambiguity — a certified plan whose intersection is not a member sorts after all members' plans; ties in insertion order — `cascades.py:49-53`
- §3.8 — insert — ambiguity — supersession tie-break on equal `created_at`: the earlier-stored plan is superseded — `cascades.py:71-73`
- §3.8 — revise — mismatch — the intersection refresh happens once per intersection after all deployments, in first-deployment order, so two plans at one intersection bump its `version` once — `cascades.py:77-85`
- §3.8 — insert — ambiguity — corridor refresh recomputes only the two numbers; stored `complaint_count_12mo` carried untouched; each corridor visited once — `cascades.py:96-105`
- §3.10 — insert — ambiguity — among plans sharing the greatest `created_at`, the last-stored is reopened — `cascades.py:129-140`
- §3.10 — insert — ambiguity — a tuning reopen retains `certified_by_user_id` and does not move `return_count` — `cascades.py:19-33,143-152`
- §3.10 — insert — ambiguity — a rounded before-mean of 0.00 yields `delay_reduction_pct` 0.00 rather than failing — `calc.py:267-270`
- §3.10 — insert — ambiguity — either AoG percentage reads 0.00 when its summed `total_arrivals` is 0; a weighted mean over zero arrivals reads 0.00 — `calc.py:294-299,256-261`
- §3.9 — insert — ambiguity — `granted_extension_sec` and the three intersection budget fields are re-derived per read, not stored; re-running the waterfall changes what other deployed configs report without refreshing their `updated_at`/`version` — `derive.py:67-88`

### Pass 3 — routes/projects.py + routes/plans.py: 9 pins, 3 mismatches
- §3.4 — insert — ambiguity — all eight travel-run fields required; `duration_sec` fractional, the three counts integers unbounded; per-field bounds before the cross-field arrivals test; no workflow-status gate — only a terminal project refuses, after body validation and before the spacing rule — `routes/projects.py:130-157`
- §3.5 — insert — ambiguity — a `SUPERSEDED` sibling neither blocks a create nor is superseded again; guard order terminal -> not-in-plan-development -> stale-version -> cycle-ceiling -> `ERR_DUPLICATE_TOD_PLAN` (absent from §2.7's ladder) — `routes/plans.py:44-59`
- §3.5 — insert — ambiguity — split adjustment: omitted/`null` keeps stored values, `phase_number`/`is_pedestrian_phase` ignored not rejected, pedestrian-triple rule re-applied to resulting values before the `DRAFT` check, the split's own `version` moves too, an empty body is still an accepted adjustment — `routes/plans.py:164-201`
- §3.5 — insert — ambiguity — split writes never consult the parent project, so a `DRAFT` plan stays editable after its project is implemented/closed/abandoned — `routes/plans.py:136,186-188`
- §3.6 — revise — mismatch — the all-`DRAFT` and at-least-one-plan gates both exclude `SUPERSEDED`; an all-superseded project is an invalid request — `routes/projects.py:273-278`
- §3.6 — revise — mismatch — `ERR_OVERSATURATED_APPROACH` is reported in preference to `ERR_CYCLE_EXCEEDS_LOCAL_MAX` (contra §2.7 rung 24/25) because saturation is tested per participant in `sequence_index` order first; a refusal on either code leaves the written-back count numbers standing — `routes/projects.py:310-322`
- §3.6 — insert — mismatch vs §2.11 — phase-split rows are mutated without `updated_at`/`version` moving (here, in the §3.8 return and the §3.10 reopen compensations); only the plan's `version` records it — `calc.py:154-160`, `cascades.py:26-27`
- §3.6 — insert — ambiguity — the pipeline answers 200 with the retiming project in `data`, not the plans — `routes/projects.py:375`
- §3.7 — insert — ambiguity — `waiver_justification` required non-blank unbounded; existing `failure_reason` retained not cleared; response carries the check — `routes/plans.py:281-297`
- §3.8 — insert — ambiguity — return `reason` required non-blank, unbounded, not persisted, response carries the plan; submission/certification/return never consult the parent project — `routes/plans.py:206-271`
- §3.10 — insert — ambiguity — `action` required and exactly `START`/`COMPLETE`, validated before either status gate; terminal project answers `ERR_PROJECT_TERMINAL` under either action; `START` leaves `last_tuning_completed_at` alone — `routes/projects.py:407-416`
- §3.10 — insert — ambiguity — evaluation supersede sweep in `created_at` ascending order; guard order terminal -> not-in-evaluation -> stale-version -> run-availability; metrics computed before any write — `routes/projects.py:231-245`
- §3.10 — insert — ambiguity — close's `note` validated non-blank/unbounded but not persisted or echoed; `disposition` decided before the project's status — `routes/projects.py:433-436`

### Pass 4 — routes/intersections, corridors, citizens, priority, observations: 14 pins, 3 mismatches
- §3.1 — insert — ambiguity — `location_name`/`controller_type` not revisable and ignored rather than rejected; omitted/`null` keeps stored value; the accessible-signal re-check fires only when the body carries `aps_installed` or `walking_speed_standard` (a `null` value still counts as carried), so an update naming neither can never report `ERR_APS_STANDARD_MISMATCH`; empty body still bumps `version`; no corridor cascade — `intersections.py:86-114`
- §3.4 — insert — ambiguity — count creation not gated on workflow status; only terminal refuses, after full body validation and before the saturation test; `count_date` unbounded; path intersection need not be a member; no `version` moves — `intersections.py:171-202`
- §3.2 — insert — ambiguity — corridor `name` uniqueness is exact, case-sensitive, untrimmed; a repeat answers `ERR_INVALID_REQUEST` — `corridors.py:30-32`
- §3.2 — insert — ambiguity — a new corridor's `avg_plan_age_days` and `complaint_count_12mo` both start at 0 — `corridors.py:38-40`
- §3.2 — insert — ambiguity — enrolment leaves the intersection's row untouched — `corridors.py:91`
- §3.2 — insert — ambiguity — screening imposes no guard on current `selection_status`, so `SCREENED -> SCREENED` re-screening is permitted — `corridors.py:123-139`
- §3.2 — insert — ambiguity — selection `rationale` validated non-blank/unbounded when supplied, not persisted, not echoed — `corridors.py:148`
- §3.3 — insert — ambiguity — requester `email` unbounded, stored verbatim, only `@` presence checked — `citizens.py:28-30`
- §3.3 — insert — ambiguity — filing moves only the new complaint's `version`; the `PublicRequester` ownership comparison is made on the raw body `requester_id` before validation, so absent/`null`/non-string yields `ERR_NOT_RESOURCE_OWNER` not `ERR_INVALID_REQUEST` — `citizens.py:69,84-90`
- §3.3 — insert — ambiguity — triage `note`, resolve `resolution_note` and reopen `reason` all optional, validated non-blank unbounded, never persisted, never echoed — `citizens.py:99,129,145`
- §3.3 — revise — mismatch — linking guard order is `ERR_COMPLAINT_INVALID_STATE` -> `ERR_PROJECT_TERMINAL` -> `ERR_COMPLAINT_PROJECT_MISMATCH` — `citizens.py:113-117`
- §3.9 — insert — ambiguity — `max_early_green_sec` lower bound is 0 — `priority.py:28`
- §3.9 — insert — ambiguity — approve/reject `note` unpersisted; `REJECT` leaves `approved_by_user_id` null; neither decision touches deployment axis, rank or allowances; only the config's `version` moves — `priority.py:66-77`
- §3.9 — insert — ambiguity — `ERR_CONFIG_NOT_DEPLOYED` is suspend's only guard; `reason` unpersisted — `priority.py:109-118`
- §3.10 — insert — ambiguity — observation window bounds both inclusive; guard order terminal -> not-in-field-tuning -> out-of-window -> round-limit; observed intersection need not be a member — `observations.py:46-56`
- §3.10 — insert — mismatch — narrows §3.10's blanket terminal-project rule: resolution gates on the observation's own status alone and never consults the project; `resolution_status` required (`OPEN` not accepted), other fields ignored, validated before the state check, 200 with the observation — `observations.py:77-87`
- §3.10 — revise — mismatch — certify checks after-study before before-study, inverting §2.7's rung 16/19 order; pinned order not-provisional -> not-in-evaluation -> invalid request on null `last_tuning_completed_at` -> `ERR_NO_AFTER_STUDY` -> `ERR_BEFORE_STUDY_INCOMPLETE`, flagged as an explicit §2.7 exception — `observations.py:90-119`

**Orchestrator verification:** `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 53 diff hunks; 105,711 -> 129,566 chars at an unchanged 495 lines), and the file ends at the completed §5 error-catalogue table (`ERR_CLOCK_NOT_MONOTONIC | 422`), not mid-sentence. Step 9 touched only `PRD_COMPLETED.md`, so the verified 8-round 104/104 sweep from Step 7 remains valid.

