# Worklog — task_2401_disaster_recovery_testing_failover_exercise

## Step 1: Create task directory — 2026-09-02T07:22:05.526Z

Created `tasks/task_2401_disaster_recovery_testing_failover_exercise/` and `tasks/task_2401_disaster_recovery_testing_failover_exercise/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:55:59.205Z

All three artifacts are complete and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2401_disaster_recovery_testing_failover_exercise/`):
- `SCAFFOLD.yaml` — 2,704 lines, §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,649 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3,114 lines, single key `scaffold_corner_design`

**Scaffold counts (§1.0–§1.7):** 14 entities, 9 state machines (Exercise carries three parallel axes: execution / data / failback), 2 OCC concurrency rules, 12 calculations, 46 ordered validations, 59 endpoints, 58 errors, 6 roles. Profile: primary archetype Graph constraint, secondary Compliance/audit, topology graph, state-machine shape parallel, role model segregation_of_duties, consistency immediate.

**§1.8:** 23 instances covering all nine `rule_id`s (2/3/2/3/3/3/3/2/2), each with executable `setup_api_calls` from an empty DB.

**§1.9:** 82 instances across all nine guide sections — entities 12, state_machines 14, calculations 12, validations 9, endpoints 5, errors 20, rbac 4, complexity_layers 5, consistency_model 1 — of which 51 carry full `test_recipe`s and 31 are `excluded_because:` stubs citing §1.8 instances by exact name. 105 instance names, all unique across both design files.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2401_disaster_recovery_testing_failover_exercise/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2401_disaster_recovery_testing_failover_exercise/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2401_disaster_recovery_testing_failover_exercise/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  1916

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Notable design decisions**
- Circular-looking impact formula resolved by one pinned forward pass: the governance surcharge keeps the *provisional* band's value even when the final score crosses into a higher band (59.50 → +3 → 62.50 requires LEVEL_3 approval but was surcharged at LEVEL_2).
- Readiness is weighted scoring with pinned rounding order (round each step contribution, then sum — three equal weight-10 steps give 99.99, not 100.00) plus a 360-day decay keyed on `RunbookStep.last_validated_at`, so re-validating a step restarts the curve while `Runbook.validated_at` stays put.
- Two independent staleness gates on scoping: readiness floor 80.00 (priority 22) and `validity_days` age (priority 39) — reachable separately via a 30-day runbook read at age 40 (88.89 passes 22, trips 39).
- Two dual-variant calculations with different selectors: achieved RTO on exercise type (WALL_CLOCK vs NET_EXECUTION, 80 vs 34 on identical timings) and achieved RPO on replication mode (REPLICATION_LAG vs TRANSACTION_GAP, 4 vs 6).
- Deliberate interval-comparator asymmetry: site windows are half-open (touching allowed, plus a 240-minute post-FULL_SITE buffer) while the group change-freeze interval is closed (touching conflicts).
- Segregation of duties enforced at four distinct rungs (tier proposer, impact approver, step owner, evidence signer) with `ERR_NOT_APPLICATION_OWNER` deliberately last at priority 46, so wrong-state and self-approval errors mask it.
- Three cascades (re-tier, second retest failure, owner suspension) all terminate in a full recompute of `Site.reserved_capacity_units` rather than an incremental delta, which is what makes the compensating invariant drift-free.

**Constraint respected:** no sibling task directory under `tasks/` was listed, read, or searched; the scaffold was derived solely from the scenario text, the skill spec, and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-02T08:55:59.205Z

Copied `INSTRUCTION.md` → `tasks/task_2401_disaster_recovery_testing_failover_exercise/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T09:12:21.805Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_2401_disaster_recovery_testing_failover_exercise/workspace/PRD.md` (484 lines) from `SCAFFOLD.yaml`. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened, grepped, or referenced.

## Sections

- **§1 Introduction** — 3 paragraphs framing the DR-assurance domain, the graph/posture model, and the SoD + logical-clock constraints.
- **§2 Global Specifications & System-Wide Principles** — 11 subsections: 2.1 Participants, Headers and RBAC · 2.2 API Response Structure (pasted verbatim) · 2.3 Pagination, Sorting and List Filters · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Segregation of Duties and Approval Authority · 2.7 Optimistic Concurrency on Recovery Groups and Exercises · 2.8 Numeric Precision and Rounding Discipline · 2.9 Validation Ordering (full 46-rank ladder) · 2.10 Cascade Discipline · 2.11 Capacity as a Shared, Recomputed Resource.
- **§3 Business Logic & Workflows** — 9 domain-titled subsections: the resilience estate · tier/RTO/RPO agreement · recovery groups, dependency mapping and critical-path projection · runbook revisions, step ownership and readiness decay · exercise scoping · production-impact approval and site reservation · execution, timing, objectives, data validation and failback · findings, re-test and the group freeze · audit evidence packages.
- **§4 Endpoint Definitions** — 4-column table, 59 rows.
- **§5 Error Code Catalogue** — 2-column table, 58 rows.

## Coverage audit

- **Contract 1 (Field-Name Coverage): PASS** — required set = 124 unique names (111 entity fields ∪ 72 request-body identifiers ∪ 36 query identifiers); `required − actual` diff is empty on the verification pass.
- **Contract 2 (Rule Coverage): PASS** — mechanically verified: all 46 validations (priority order, error id, HTTP status, `applies_to` scope) reproduced in the §2.9 ladder; both OCC rules with required version fields and 412 errors; all 9 state machines / ~70 transitions including guards (`STALE → IN_REVIEW` requires no `INVALIDATED` step; `VALIDATE` requires every step `VALIDATED`), the `VALIDATED → VALIDATED` re-validation, and both `VALIDATED → SUPERSEDED` and `STALE → SUPERSEDED`; all 12 calculations with pinned orders (readiness rounds per-contribution then sums — 99.99 not 100.00; impact surcharge keyed on the *provisional* band and `required_approval_level` derived once from the *final* score); both dual-variant calculations with symmetric sibling branches (`WALL_CLOCK`/`NET_EXECUTION`, `REPLICATION_LAG`/`TRANSACTION_GAP`); all three cascades hop-by-hop including the capacity-release asymmetry (only cancels out of `SCHEDULED` release units); every endpoint `side_effects` entry; all entity defaults, ranges and nullability. 58/58 errors present with matching status codes; 59/59 endpoints present with exactly matching role sets.
- **Contract 3 (§3 Path Purity): PASS** — 0 backticked tokens beginning with `/`, 0 bare HTTP method tokens, 0 method+path combinations in §3.

Also clean: no fuzzy quantifiers ("approximately", "roughly", "conservatively") and no symbolic operators (`==`, `>=`, `+=`, `min()`, `ceil()`, `round()`, bare `AND`/`IN`) anywhere in the document — all translated to prose. One gap found and fixed during audit: `step_number`'s minimum of 1 was initially omitted.

## Step 5: Generate unit tests — 2026-09-02T10:41:05.000Z

All work is complete. Final verification passed.

## Files written

**`test_helpers/`** (9 modules): `__init__.py`, `api_client.py` (one method per endpoint, 61 endpoints), `api_errors.py` (58-entry catalogue + HTTP status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (staged estate builders + 20 scenario builders), `test_users.py`, `types.py`.

**`test_suite/`**: `conftest.py` + 12 test modules, **97 tests**:

| file | tests | source |
|---|---|---|
| test_01_dependency_graph_and_readiness_scoring | 8 | queue A |
| test_02_exercise_scoping_precedence | 8 | queue A |
| test_03_impact_approval_and_site_capacity | 10 | queue A |
| test_04_execution_axes_and_measurement | 10 | queue A |
| test_05_findings_and_cascading_ripples | 10 | queue A |
| test_06_estate_registers_and_reads | 12 | Corner/entities |
| test_07_lifecycle_transitions_and_terminal_states | 8 | Corner/state_machines |
| test_08_objectives_manifests_and_decay_curves | 5 | Corner/calculations + consistency_model |
| test_09_validation_ladder_precedence | 5 | Corner/validations |
| test_10_endpoint_behaviours | 5 | Corner/endpoints |
| test_11_rejection_catalogue | 10 | Corner/errors |
| test_12_role_boundaries_and_concurrency | 6 | Corner/rbac + complexity_layers |

## Counts per queue

- **Queue A (difficulty)**: 23 instances, zero stubs → **46 tests** (2 per instance).
- **Queue B (corner)**: 51 non-stub instances → **51 tests** (1 per instance). The 31 stub instances carrying `excluded_because` were not translated, as specified.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated.

Two design-index defects were worked around rather than skipped, since neither affects the asserted outcome: several recipes use finding `severity` `MAJOR`/`MINOR`, which are not in the PRD's declared set (`CRITICAL | HIGH | MEDIUM | LOW`) — translated as `HIGH`/`MEDIUM`; and two recipes name RTO/RPO measurement variants `NET_EXECUTION`/`REPLICATION_LAG`, identifiers absent from the PRD — asserted against the PRD's own prose definitions (net hands-on time; replication lag) instead.

## Coverage audit

Machine-checked against both design YAMLs and `workspace/PRD.md`:

- **149 docstring PRD quotes**, all surviving literal (whitespace-normalised) grep against the PRD — 0 missing.
- **97 tests, 97 `Design:` tags**: exactly one per test, always the last docstring line, every tag resolving to a real non-stub instance. 0 untagged, 0 dual-tagged, 0 stub-tagged, 0 dangling.
- Difficulty instances with fewer than 2 tests: **0**. Corner non-stub instances with 0 tests: **0**.
- All imports, `api.*`/`fx.*`/`f.*` attributes and all 58 `ApiErrorId` members resolve statically; suite byte-compiles clean; no unused imports; no mention of the scaffold anywhere in generated code.

## Defects found and fixed while generating

1. `EvidencePackage`'s field is `state`, not `status` (PRD L351/L161) — 4 assertions corrected in `test_04` and `test_07`.
2. PRD L89: an asset's replication-observation log is the API's single exception to `created_at` ASC ordering — returned most-recent `observed_at` first. The `test_06` ordering assertion was inverted and is now correct, with the exception sentence cited.
3. `ApiErrorId` enum members were declared without the `ERR_` prefix while all 12 test modules referenced `ApiErrorId.ERR_*` — every call would have raised `AttributeError`. Members renamed so name and value match; all 58 references now resolve.

## Step 6: Generate implementation — 2026-09-02T10:22:00.000Z

The implementation is complete and boot-verified.

## Files written
`workspace/implementation/`
- `app.py` — Flask factory, blueprint registration, `ApiError`/404/405/HTTPException/500 handlers, `PORT` from env
- `start.sh` — guarded `pip install` (only when Flask is absent, to avoid boot contention under per-test restarts) then `exec python3 app.py`; `requirements.txt`
- `db.py` — in-memory `Store` (14 dicts, empty at boot, nothing seeded), logical clock defaulting to `2026-08-01T00:00:00Z`, `new_row`/`touch`/`sort_key`, ISO formatting with 3 fractional digits
- `constants.py`, `errors.py` (all 59 error ids → HTTP), `response.py` (meta/envelope), `middleware.py` (ranks 1–3), `validation.py` (ranks 4–6, pagination, filters)
- `services.py` — every derived calculation: readiness decay, critical path, posture derivation, impact score, capacity, achieved RTO/RPO, manifest count, cycle detection, interval helpers, cascades A/B/C
- `routes/__init__.py`, `routes/estate.py`, `routes/groups.py`, `routes/exercises.py`, `routes/audit.py`

## Endpoint count
**59 routes**, verified programmatically to be a one-to-one match with the SCAFFOLD endpoint table — no missing, no extra paths, and **every endpoint's role list matches the scaffold exactly**.

## Notable design decisions
- `created_at`/`updated_at` and all age/window math read the **logical clock**; only `meta.api_request_timestamp` uses real UTC. A hidden `_seq` breaks ties when logical timestamps are identical.
- At most **one version bump per row per request** (dedup set in `flask.g`); rows created in the request stay at version 1. Explicitly declared bumps (`group-assignments`, `change-freeze`, `POST /runbooks`, scope-items, HARD edge → containing group) always touch; derived recomputes touch only on actual change.
- Rank 5 (body FK existence) fires only for non-empty strings, so absent/null falls through to rank 6 (400). Polymorphic dependency-edge FKs pick their register from the validated discriminator.
- Rounding pinned: readiness rounds per step and per contribution but **never the final sum** (3×weight-10 steps → 99.99, verified); impact is a single forward pass with the surcharge keyed on the **provisional** band and `required_approval_level` from the **final** score.
- Site `reserved_capacity_units` is always a **full recomputation** from the exercise table, never a delta.
- Interval semantics: exercise `[start,end)` vs freeze `[fs,fe]` closed → conflict iff `start <= fe and fs < end`; site overlap half-open; plus the 240-minute FULL_SITE post-window buffer.
- Evidence packages check SEALED **before** the from-state (otherwise rank 15 would mask rank 16 forever), and the action↔actor split (SUBMIT/RETURN/SEAL = AuditLiaison, SIGN_OFF = RiskApprover) yields 403 before the state checks.
- Finding rank-14 from-state is checked **before** action-conditional payload fields, so a wrong-state request with a minimal body still returns 409. `CLOSE` has no declared from-state (CLOSED is reached only via a passing retest) and therefore always reports the state error.
- Undeclared edges resolved as: SUSPENDED owner on ASSIGN → `ERR_INVALID_REQUEST`; finished retest exercise → `ERR_INVALID_EXERCISE_STATE` before rank 32; `COMPLETE_FAILOVER` with zero step executions → `ERR_INVALID_EXERCISE_STATE` before rank 43.

## Boot / behaviour verification
`PORT=18821 bash start.sh` and `PORT=18822 bash start.sh` both booted cleanly from a fresh process (the host is heavily loaded — ~290 sibling `app.py` processes — so first listen took ~10 s, well within a normal harness wait) and served `GET /sites` → 200 with a correct envelope. Two end-to-end scripted suites then ran against them with **0 failures**, covering: full happy path (tiering → group → runbook validation → scoping → impact → schedule → execute → data/failback axes → close → findings → evidence seal), OCC 412s on both endpoints, cascade A (re-tier), cascade B (double retest failure → FROZEN → exercise cancelled → capacity released), cascade C (owner suspended → steps invalidated → runbook STALE), readiness 99.99 and 88.89 decay values, impact 27.00/28.00 and 53.00/56.00 with LEVEL_2 authority refusal, RTO/RPO objectives and achieved values (SKIPPED excluded, ceil semantics), runbook supersession, validity expiry, change-freeze endpoint touching, window overlap, the 240-minute buffer, capacity exhaustion and release, pagination/meta and 400/401/404 envelopes. Both servers were killed and `__pycache__` removed afterwards.

## Step 7: Run tests and iterate — 2026-09-02T13:52:00.000Z

Resumed pipeline: filesystem inspection showed Steps 2-6 all satisfied (three non-empty SCAFFOLD files, workspace/INSTRUCTION.md, a complete workspace/PRD.md ending in the full error catalogue table, test_suite/ with 12 test_*.py files, test_helpers/ with 9 modules, and workspace/implementation/ with app.py + start.sh + routes/). No Step 7 worklog entry existed, so the loop was (re-)run per the always-run rule. Stale `results.{1,2,3,4,5,7,8}.json` from the previous interrupted run (59/97, 50/97, 51/97, 61/97, 64/97, 59/92, 55/94 — note the differing totals) were deleted before the first sweep.

Subagent summary, verbatim:

Clean sweep achieved.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (16 rounds total, 1552 test executions).

**Final gate result:** all 8 rounds `97 passed / 0 failed / 97 total`. Round totals were stable at 97 in every round of both sweeps — the 92/94/97 collection variance the previous agent saw was purely an artifact of editing files mid-sweep, not a real collection problem.

**Tests deleted:** none. No test reached STEP 1 of the diagnostic protocol, because no assertion ever tripped.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### What actually happened

The prior agent's "~55-64 of 92-97 passing" reading was untrustworthy, exactly as flagged. My fresh sweep 1 came back at 97/97 in six rounds and 96/97 in two (rounds 6 and 8), a union of exactly 2 failing tests:

- `test_11_rejection_catalogue.py::test_the_same_pair_may_be_re_added_only_under_the_other_edge_kind`
- `test_03_impact_approval_and_site_capacity.py::test_cancelling_an_approved_exercise_leaves_the_site_untouched`

Both failed with a bare `requests.exceptions.ConnectionError: ConnectionResetError(104)` at the urllib3 transport layer — no assertion reached, no response body, different tests in different rounds. I confirmed this was not sweep reaping: the sweep ran under `setsid nohup`, the server logs contained only `Killed` (the runner's own `kill -9`) and never `Terminated`, and the two failures were 5 minutes apart rather than at one wall-clock instant. Host load average was 40-75 on 32 cores at the time. Neither test contains any timing or concurrency logic — both are strictly sequential request chains.

Per the load-induced guidance I re-swept with zero edits, and all 8 rounds came back 97/97. Confirmed transport flakiness from host CPU contention, not an implementation or test defect.

I also spot-verified two cardinal-rule invariants while sweeps were in flight: `workspace/implementation/db.py` holds all 14 registers in plain dicts with an empty `reset()` at boot (no seeding, no disk persistence, logical clock defaulting to `2026-08-01T00:00:00Z` per PRD §2.4), and `workspace/implementation/app.py` binds `$PORT` with no hardcoded entity data.

**Cleanup:** removed the leftover `run_subset.sh` scratch helper from the previous agent, plus my own sweep logs, `results.*.json` files, and stale `__pycache__` directories. The task tree now holds only the three SCAFFOLD files, `worklog.md`, `test_helpers/`, `test_suite/`, and `workspace/` (PRD.md, INSTRUCTION.md, implementation/).

One note for the record: `worklog.md` has no Step 7 entry covering this test-and-fix loop. I did not add one since nothing was changed, but if the pipeline expects a per-step log entry you may want that appended.

### Orchestrator note

The subagent's cleanup removed the final `results.*.json` files, which the skill's output tree expects as passing evidence. The orchestrator re-ran one confirmation sweep (under `setsid nohup`, zero edits to any artifact) concurrently with Step 9 — safe because Step 9 only reads `implementation/` and writes `workspace/PRD_COMPLETED.md`, and never mutates the code or tests a sweep is exercising.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:52:30.000Z

Skip condition met. Step 7 reported 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — no artifact was modified at any point in the loop. The second sweep was a zero-edit re-confirmation that two `ConnectionResetError(104)` transport failures were host-CPU-contention flakiness, not a defect, so it does not constitute an iteration beyond the baseline. `<step_7_diff>` would therefore be empty and Step 8's subagent would have no focus list to work from: `PRD.md` already uniquely determined every behavior the implementation exhibits at every site the test suite exercised. `PRD_FINALIZED.md` is intentionally absent, and Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T14:05:00.000Z

Ran from `PRD.md` (no `PRD_FINALIZED.md`, Step 8 skipped). Subagent summary, verbatim:

`PRD_COMPLETED.md` is written. Structure is preserved exactly: 28 headings, 121 table rows, 57 validation-ladder items — no new sections, table rows or ranks.

**Counts**
- `PRD.md`: 484 lines / 89,680 chars → `PRD_COMPLETED.md`: 489 lines / 100,472 chars (+5 lines, +10,792 chars)
- Ambiguity-pins: 34 · Mismatch-revisions: 6

**Changes** (all paths relative to `workspace/`)

- §2.1 — insert — ambiguity — an empty header value counts as absent for `ERR_UNAUTHENTICATED` — implementation/middleware.py:20
- §2.2 success — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — implementation/response.py:16
- §2.2 success — insert — ambiguity — `api_request_timestamp` is the one timestamp read from real wall-clock, not the logical clock — implementation/response.py:22
- §2.2 error — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405, unparseable/absent body read as `{}` — implementation/app.py:28,33; implementation/validation.py:12
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty string falls back to default — implementation/validation.py:143
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation sequence; observation log ties by greater `created_at` then later row — implementation/db.py:144; implementation/routes/estate.py:434
- §2.3 — insert — ambiguity — enum-valued filters reject undeclared values with `ERR_INVALID_REQUEST`; id-valued filters accept any string; empty filter ignored — implementation/validation.py:163
- §2.4 — insert — ambiguity — clock accepts any well-formed instant forwards or backwards, absent/malformed → `ERR_INVALID_REQUEST`, response `data` is `{current_utc}`; `created_at`/`updated_at` also read the clock — implementation/routes/audit.py:330; implementation/db.py:110
- §2.5 `version` bullet — insert — **mismatch** — `version` increments at most once per row per request; rows minted by the request stay at 1 — implementation/db.py:122,108
- §2.5 derived-fields para — insert — **mismatch** — a recompute landing on the stored value is not a mutation (no `updated_at`/`version` move); the five endpoints that version unconditionally are named — implementation/services.py:100,115,171,209
- §2.5 — insert — ambiguity — `rationale`/`decision_note`/`note`/`validation_note`/`scheduling_note`/`reason` are validated then discarded; `StepExecution.notes` is the only stored free text — implementation/routes/estate.py:240; implementation/routes/exercises.py:466
- §2.9 ranks 15–16 — revise — **mismatch** — seal check evaluated *ahead* of the evidence from-state check (order swapped) — implementation/routes/audit.py:284
- §2.9 rank 35 — insert — ambiguity — codes and `email` compared as exact case-sensitive strings — implementation/routes/estate.py:47
- §2.10 cascade A hop 5 — insert — ambiguity — fires only on the transition out of `READY` — implementation/services.py:266
- §2.10 cascade B hop 4 — insert — ambiguity — fires only on the transition into `FROZEN` — implementation/services.py:264
- §3.1 stakeholder patch — insert — ambiguity — all three fields optional; a field-less patch still versions the row and answers 200 — implementation/routes/estate.py:85
- §3.1 application creation — insert — ambiguity — `proposed_tier`/`proposed_rto_minutes`/`proposed_rpo_minutes`/`proposed_by_id` also start null — implementation/routes/estate.py:191
- §3.2 tier agreement — insert — ambiguity — recomputes only the projection; no posture re-derivation, conditional group versioning — implementation/routes/estate.py:299
- §3.2 group assignment — revise — ambiguity — unconditional group version bump, re-assignment permitted, former group untouched, no posture re-derivation — implementation/routes/estate.py:317,393
- §3.3 group creation — insert — ambiguity — `change_freeze_start_at`/`_end_at` start null — implementation/routes/groups.py:72
- §3.3 posture derivation — insert — ambiguity — reads the stored `readiness_score`, never recomputes on its own account — implementation/services.py:250
- §3.3 posture re-run set — revise — **mismatch** — enumerates exactly which requests re-derive posture; membership/calendar writes and finding creation do not — implementation/routes/*.py
- §3.3 projection tie-break — insert — ambiguity — creation-sequence tie-break and prefix-path rule (shorter path wins) — implementation/services.py:149
- §3.3 posture refresh — insert — ambiguity — versions group/runbook only where a value actually moved — implementation/routes/groups.py:126
- §3.5 exercise creation — insert — ambiguity — `closure_reason` starts `NONE`; explicit list of null-at-creation fields — implementation/routes/exercises.py:76
- §3.5 scope-item readiness — insert — ambiguity — the pre-check recompute persists on the runbook even when the scope item is rejected — implementation/routes/exercises.py:155
- §3.5 change-freeze bar — revise — ambiguity — both ends closed (`start <= freeze_end and freeze_start <= end`); a null freeze never conflicts — implementation/services.py:517
- §3.6 impact submission — insert — ambiguity — scopeless submission → `ERR_INVALID_EXERCISE_STATE`, before any group is examined — implementation/routes/exercises.py:247
- §3.6 capacity component — insert — ambiguity — `usable_capacity_units` 0 yields 0.00 rather than dividing — implementation/services.py:368
- §3.6 scheduling cool-down — insert — ambiguity — band closed at the lower end, open at the upper; directional and predecessor-type-keyed — implementation/routes/exercises.py:339
- §3.7 `COMPLETE_FAILOVER` — insert — ambiguity — step-execution precondition → `ERR_INVALID_EXERCISE_STATE`, checked before data stores — implementation/routes/exercises.py:415
- §3.7 observation selection — insert — ambiguity — final tie-break is the later-appended row — implementation/services.py:436
- §3.7 RPO skips — insert — ambiguity — stores with no qualifying observation skipped by either variant; 0 when nothing is measurable — implementation/services.py:446
- §3.8 finding transitions — revise — ambiguity — payload checks follow the from-state check; `ASSIGN`/`REMEDIATE`/`RECORD_RETEST_RESULT` shortfalls → `ERR_INVALID_REQUEST`; finished re-test nominee → `ERR_INVALID_EXERCISE_STATE` before the scope test; `retest_result` validated first — implementation/routes/audit.py:141
- §3.8 `CLOSE` — insert — ambiguity — declares no from-state, so always `ERR_INVALID_FINDING_STATE` — implementation/routes/audit.py:118
- §3.8 count/posture — revise — **mismatch** — every finding transition recomputes `open_finding_count` and re-derives posture, not only terminal moves — implementation/routes/audit.py:186
- §3.8 thaw wording — revise — ambiguity — readiness read "as last written" rather than "as of the current logical clock" — implementation/services.py:250
- §3.9 evidence transitions — insert — ambiguity — per-action actor (`SUBMIT`/`RETURN`/`SEAL` = AuditLiaison, `SIGN_OFF` = RiskApprover) → `ERR_UNAUTHORIZED`, after shape validation and before the seal/state checks — implementation/routes/audit.py:277
- §3.9 seal ordering — revise — **mismatch** — seal check precedes the from-state check — implementation/routes/audit.py:284
- §4 status codes — revise — ambiguity — the three 200 writes are exhaustive; change-freeze and every transition/submission/decision/schedule answer 201 — implementation/routes/groups.py:123 and peers

No files under `implementation/`, `test_suite/` or `test_helpers/` were touched.

### Orchestrator note — evidence sweep

The confirmation sweep launched alongside Step 9 completed while Step 9 was running: `results.{1..8}.json` all report `97 passed / 97 total`, restoring the passing evidence the Step 7 subagent had cleaned up. This is the third independent 8-round sweep to come back fully green (24 rounds, 2328 test executions, zero artifact edits between them). Pipeline complete.
