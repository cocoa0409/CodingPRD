# Worklog — task_2221_hotel_pre_opening_program_management

## Step 1: Create Task Directory — 2026-09-01T05:33:18.275Z

Created `tasks/task_2221_hotel_pre_opening_program_management/` and `tasks/task_2221_hotel_pre_opening_program_management/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T07:12:38.635Z

All three artifacts are complete and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD.yaml` (§1.0–§1.7; contains neither design key)
- `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## SCAFFOLD.yaml surface
`domain_name: hotel-pre-opening`, `api_prefix: /pre-opening`, `difficulty_level: expert_plus`, `primary_archetype: graph_constraint` / `secondary: posture_driven_gating`, `entity_topology: graph`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = cascading_side_effects, dual_variant_calculation, optimistic_concurrency, derived_field_reconciliation.

- **13 entities**: PreOpeningProgram, Milestone, MilestoneDependency (junction, `common_fields: false`), PermitApplication, SystemImplementation, SystemTestRun, DepartmentHiringPlan, Hire, TrainingSession, BudgetLine, OseOrder, ReservationBlock, PunchListItem
- **10 state machines / 47 transitions** (program carries two independent dimensions: schedule_state and commercial_state; permit deficiency and punch reopen/reject cycles are cyclic)
- **7 calculations**: critical_path_schedule (dual-variant OPTIMISTIC/COMMITTED), cost_at_completion (dual-variant COMMITMENT/ACCRUAL basis), readiness_posture (4-term weighted score), system_test_aggregation, contingency_liability (tiered admin fee), storage_overlap_load, training_room_occupancy
- **14 ordered validations**, **59 endpoints**, **61 error codes**, **8 roles**, **2 concurrency rules** (`expected_program_version` on block create, `expected_budget_line_version` on OSE-order create)

## §1.8 rule coverage — 24 instances, all 9 rules ≥ 2
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

## §1.9 section coverage — 91 instances, all 9 guide sections
entities 11, state_machines 13, calculations 11, validations 8, endpoints 5, errors 27, rbac 8, cross-cutting complexity layers 7, consistency model 1 — of which 72 carry full `test_recipe` chains and 19 are `excluded_because` stubs pointing at §1.8 instances by name (all references resolve; no stub carries a `test_recipe`). Every one of the 61 error codes is triggered by at least one §1.8/§1.9 instance. All instance names are unique across the union of both design files; every recipe instance has `grounds` (list), `distinguishing_aspect`, and `test_recipe: {setup, setup_api_calls, trigger, assert}`.

Two fixes worth flagging: the word "simultaneously" in the Kahn tie-break comment of `critical_path_schedule` was rewritten (forbidden vocabulary), and 18 stub names that duplicated their §1.8 counterparts were renamed for cross-file uniqueness.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  852

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-09-01T07:12:38.635Z

Copied `INSTRUCTION.md` → `tasks/task_2221_hotel_pre_opening_program_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T07:22:23.773Z

Both hits are the ordinary preposition ("explicit about the arithmetic", "nothing about the commercial dimension"), not approximation hedging — no fix needed.

## Done

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/workspace/PRD.md` — 412 lines, ~12,100 words. Ends at §5; no audit footer.

### Structure
- **§1 Introduction** — 3 paragraphs (pain-point → scope → the two-state-dimension organizing idea).
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 Operator Identity & RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties & the Logical Clock, 2.5 Program Scoping / Referential Integrity / Nested Retrieval, 2.6 Readiness Posture: The Derived Gate, 2.7 Dual-Variant Projection & Derived-Field Reconciliation, 2.8 Money/Rounding/Dates/Ratio Precision, 2.9 OCC on the Two Finite Pools, 2.10 Order of Validation, 2.11 Segregation of Duties.
- **§3 Business Logic** — 9 subsections grouped by pre-opening workstream: program setup, construction network, baselining & the two schedule projections, licensing + deficiency cascade, systems/test evidence/certification, staffing waves & training, budget/OS&E/cost-at-completion, reservation ramp & contingency, punch list → soft opening → stabilization.
- **§4** 59-row endpoint table (4 columns). **§5** 61-row error table (2 columns).

### Hard Contracts — all PASS

```
Field coverage check:
- entities[].fields: 132 required, 132 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in prose (§2.10 ordered 14-tier list), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_program_version / expected_budget_line_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 47 checked (10 machines), 47 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (both schedule variants, both cost bases, tiered contingency, weighted posture, test aggregation, storage overlap, room turnover), 0 missing
- validations[] conditions: 61 error ids checked, 61 matchable to trigger in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 59 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 132 checked, defaults/initials/constraints reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (ISSUE|DEFICIENCY, ACCEPT|DECLINE|WITHDRAW, VERIFY|REJECT, RELOCATE|CANCEL, receive|cancel, FINISH_START|START_START in both passes, OPTIMISTIC|COMMITTED, COMMITMENT|ACCRUAL, 2 OCC rules), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 864
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches the canonical source byte-for-byte; all 10 state machines' state strings and all enum-field values present verbatim; all 8 role names present with `identity: opaque` translated (plus the six fields where `X-User-ID` is recorded); no fuzzy/approximating language (the two " about " hits are the ordinary preposition).

Three gaps found during the Contract 2 walk and repaired: (1) the `SOFT_OPENING → LICENSING` freeze compensation was only stated for the critical-punch-reopen path — now stated generally in §2.6 for either freeze cause; (2) `actual_duration_days` retention on the `COMPLETE → BLOCKED` deficiency hop was implicit — now explicit; (3) the two OCC rules named their endpoints only by capability — now the exact paths appear in §2.9 (permitted, since Contract 3 polices §3 only).

I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Step 5: Generate Unit Tests — 2026-09-01T08:06:19.372Z

Suite complete and verified.

## Files written

**`test_helpers/`** (8 modules + `__init__.py`): `constants.py` (states, enums, weights, thresholds, roles), `api_errors.py` (all 61 error ids + HTTP status map, registered with the shared validators at import), `api_client.py` (`PreOpeningApiClient`, one method per PRD endpoint), `test_users.py` (per-role headers + distinct second actors for the three duty-separation rules), `types.py`, `factories.py` (payload builders where a `None` override drops the key), `assertions.py` (domain assertions incl. ratio precision tighter than 4 dp), `fixtures.py` (5-tier scenario builders from empty DB through public endpoints only).

**`test_suite/`** — `conftest.py` + 13 test files, **153 test functions / 174 collected cases**:

| file | tests |
|---|---|
| test_01_schedule_and_cost_projections.py | 12 |
| test_02_program_lifecycle_cascades.py | 13 |
| test_03_rule_precedence_and_boundaries.py | 23 |
| test_04_cross_entity_gates_and_reversals.py | 18 |
| test_05_records_and_field_defaults.py | 12 |
| test_06_entity_state_transitions.py | 10 |
| test_07_derived_calculations.py | 9 |
| test_08_input_and_business_validations.py | 8 |
| test_09_endpoint_read_models.py | 5 |
| test_10_resource_and_state_errors.py | 10 |
| test_11_gate_and_ceiling_errors.py | 12 |
| test_12_role_permissions_and_duty_separation.py | 12 |
| test_13_concurrency_versioning_and_consistency.py | 9 |

## Coverage

- **Queue A (difficulty): 24/24 instances**, every one with ≥2 tests (18 have 3).
- **Queue B (corner): 72/72 non-stub instances**, each with ≥1 test; all **19 `excluded_because:` stubs received 0 tests** and all 19 cross-references were verified to resolve to real difficulty-instance names.
- **Instances skipped: none.**

## Verification performed

- Every test has exactly one `Design:` line, last in its docstring; all 153 tags resolve to existing instances; none tags a stub; no dual or malformed tags.
- Citation pass: every docstring contains a verbatim ≥8-word window of `workspace/PRD.md` (0 failures).
- Scaffold-citation pass: no reference to scaffold, `SCAFFOLD.yaml`, "Table 1", or scaffold section numbers anywhere in emitted code.
- No `skip`/`xfail` markers. `pytest --collect-only` → 174 tests, no import or collection errors. Implementation directory never read.

## Notable judgement calls

- One corner instance (`errors/authorize_soft_opening_reports_the_system_gate_before_the_department_gate`) was initially skipped by a worker as non-derivable; I overruled that after reading §2.10 — tier 10 explicitly names "every required system certified" while `ERR_DEPARTMENT_NOT_READY` appears in no tier, and §3.9 enumerates the two gates in that order — and wrote the test myself (`test_11`, `TestSoftOpeningGateOrder`).
- Across all files, **absolute `version` literals** from the design recipes were replaced with `previous + 1` deltas, because §2.4 makes a derived-field recomputation a version-incrementing mutation of its owner, so absolute counts are not uniquely derived. Budget-line absolute versions *are* derivable and are asserted exactly.
- Exact timestamp literals (`onboarded_at`, `received_at`, `submitted_at`) are asserted via `is_iso8601_timestamp` plus a date/second prefix, since §2.4 mandates three fractional digits.
- Dependency-edge `?role=` filter assertions were dropped (the PRD never pins the token spelling); the equivalent behaviour is proven by listing incident edges from both milestones.

## Step 6: Generate Implementation — 2026-09-01T08:06:19.372Z

The implementation is complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/workspace/implementation/`)

**Launcher / infra:** `start.sh` (installs Flask only if missing, `exec python3 app.py`, honors `PORT`, default 10000, binds 0.0.0.0), `requirements.txt`, `app.py` (app factory, per-request version-bookkeeping hooks, `ApiError`/404/405/400/500 handlers).

**Support layer:** `errors.py` (61 catalog codes + 3 infra codes with HTTP statuses), `clock.py` (logical clock pinned at `2026-08-01T00:00:00Z`, never falls back to wall time for business instants), `db.py` (pure in-memory dicts, snapshot-diff `version`/`updated_at` bookkeeping so each record bumps at most once per request), `response.py`, `middleware.py` (8 peer roles, opaque identity), `validate.py`, `repo.py`, `guards.py`, `tx.py`.

**Domain services:** `services/schedule.py` (Kahn topological sort + forward/backward pass, OPTIMISTIC/COMMITTED variants, float/criticality/slip), `services/derive.py` (test aggregation, plan/session counters, tiered cancellation contingency, dual-basis cost at completion, readiness score/posture and the freeze cascade).

**Routes:** `routes/programs.py`, `milestones.py`, `permits.py`, `systems.py`, `staffing.py`, `budget.py`, `reservations.py`, `punchlist.py`, `clock_route.py`.

## Endpoint coverage
**59/59** — a programmatic diff of the Flask URL map against `SCAFFOLD.yaml` `endpoints` (method + path, ids normalized) reports zero missing and zero extra, including `POST /_clock/set_current_utc`.

## Storage
In-memory Python dicts only (`db.Store`). No SQLite, no disk JSON, no `/tmp` cache, no seeding — every boot starts with all 13 collections empty (verified: `GET /pre-opening/programs` on a fresh process returns `[]` with `total_count: 0`).

## Boot verification
`PORT=18321 bash start.sh` came up in under 3s; `GET /pre-opening/programs` → 200 with the correct envelope and pagination meta, `POST /_clock/set_current_utc` → 200 `{"current_utc":"2026-09-09T12:00:00.000Z"}`; process then stopped and the port released.

## Behavioral smoke test (in-process, full lifecycle)
Exercised program create → milestones + dependencies (duplicate and cycle both rejected 422) → baseline → start/complete → all 4 mandatory permits including a DEFICIENCY cycle → 2 systems with prerequisite chain and SoD certification → hiring plan/session/hires through ONBOARDED → budget line + OS&E order/receive → booking open, block accept/guarantee → CRITICAL punch freeze → verify/recover → soft opening → STABILIZED. Confirmed: the five-link permit freeze cascade (posture FROZEN, `BOOKING_OPEN→BOOKING_SUSPENDED`, pre-opening blocks `→AT_RISK` with the right reason), tier-2 contingency math (1,200,000 base + 8% = 1,296,000, +50,000 guarantee penalty), both OCC guards (412), all three SoD prohibitions (403), the 30-minute turnover buffer (exact-adjacency rejected, +30 min accepted), storage/headcount/wave ceilings, and the global STABILIZED mutation lock (409).

Two defects found and fixed during this pass: budget-line `committed_cents`/`spent_cents` are now reconciled from their orders rather than incremented in the routes, and a block swept `GUARANTEED→AT_RISK` now retains the guarantee penalty in `contingency_cents` (tracked via a non-serialized `_guaranteed` marker, cleared on AT_RISK→ACCEPTED recovery).

## Step 7: Run Tests and Iterate — 2026-09-01T08:27:24.521Z

All 8 parallel rounds now pass: **174/174 in every round**, 0 failures, 0 errors.

## Summary

**Iterations run:** 2 (sweep 1 → diagnosis + fixes → sweep 2 clean)

**Tests deleted:** none. Every failing test survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); all 16 failures were test-plumbing/precondition bugs, not PRD-silence bugs.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none. In particular the PRD §3.2 milestone-creation guard in `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/workspace/implementation/routes/milestones.py::create_milestone` was left intact — it was correctly rejecting a non-PRD-conformant test setup.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/test_suite/test_07_derived_calculations.py` — 16 sites: replaced the double-unwrap `get_success_data(validate_success(resp, expected_status=N))` with `validate_success(resp, expected_status=N)`. `validate_success` already returns the unwrapped `data`, so feeding it into `get_success_data` raised `AttributeError: 'dict'/'list' object has no attribute 'status_code'` before any assertion could run. 9 tests fixed; no assertion weakened (status + envelope still validated).

2. `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/test_suite/test_08_input_and_business_validations.py` — same double-unwrap at 6 sites (lines 80, 153, 259, 326, 385, 441). 6 tests fixed.

3. `/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/test_suite/test_13_concurrency_versioning_and_consistency.py` — `TestVersionAdvancesOnEveryProgramWrite::test_each_program_write_advances_the_token_by_exactly_one`: removed a `fixtures.make_milestone(..., code="INTERIOR_FIT_OUT", ...)` setup call issued *after* `construction_complete_program` had driven `schedule_state` to `CONSTRUCTION_COMPLETE`. PRD §3.2 states verbatim: "Milestones may only be added while the program's delivery dimension is `PLANNING` or `BASELINED`; once the program has reached `CONSTRUCTION_COMPLETE` no further milestone may be created for it, and the attempt is refused with `ERR_INVALID_PROGRAM_STATE`." The setup was the bug (STEP 2, TEST IS WRONG); the milestone was not needed by any assertion, and the surviving version-increment assertions (open-booking +1, suspend-booking +2, recompute-schedule +3) still hold because the fixture already creates one milestone so `recompute-schedule` cannot hit `ERR_SCHEDULE_EMPTY`.

**Flakiness finding:** zero. Sweep 1 was perfectly deterministic (all 8 rounds identically 158/174 with the same 16 failures) and sweep 2 is identically 174/174 across all 8 rounds — no concurrency race, fixture-ordering, or port-collision sensitivity surfaced.

## Step 8: Finalize PRD — 2026-09-01T08:30:25.491Z

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/workspace/PRD_FINALIZED.md` exists and is a **byte-identical copy** of `PRD.md` (md5 `a422e7e6e44896bea38739d5326a98fd` for both).

- PRD.md: 411 lines. PRD_FINALIZED.md: 411 lines. Delta: 0 lines, **0.00%**.
- Change bullets: **none**. Every `<step_7_diff>` item traced to a test-plumbing or test-precondition bug, not to a PRD silence or a PRD/impl divergence.

## Per-item analysis (subject identified → impl paths enumerated → verdict)

**Item 1 — `test_07_derived_calculations.py`, 16 double-unwrap sites (9 tests).**
(a) Subject: nothing behavioral — `get_success_data(validate_success(...))` fed an already-unwrapped `data` dict back into a helper expecting a `Response`, raising `AttributeError` before any assertion executed. The fix restores the assertions unchanged.
(b) Enumerated: I read the whole test file to confirm no assertion that only *began running* after the fix pins an impl choice PRD leaves open. Every revived expectation quotes PRD verbatim and is uniquely derivable from it — per-hire payroll accrual set and rounding (§2.8/§3.7), the 0.50 demotion floor and 0.95 certification floor (§3.5), latest-run selection by greatest `executed_at` (§3.5), `readiness_score` half-up at four decimals (§2.6), forward/backward pass on a two-predecessor join (§3.3), and the pinned contingency evaluation order (§3.8). Cross-checked the impl surfaces the tests newly touch: `implementation/routes/programs.py:188` (`recompute_schedule`), `:198` (`open_booking`), `:228` (`suspend_booking`), `implementation/services/derive.py`, `implementation/services/schedule.py`.
(c) No wording adjustment — no edit.

Note on one latent ambiguity I deliberately did **not** pin: PRD §3.5's "if the new run's `latest_pass_rate` is below 0.50" can be read as the appended run's own `pass_rate` or as the system's post-aggregation `latest_pass_rate` (which, for an out-of-order append, is a different run). `test_latest_pass_rate_reads_the_greatest_executed_at` yields `TESTING` under **both** readings (0.75 and 1.0 are both ≥ 0.50), so the Step 7 fix revealed no divergence there. Pinning it would be out of HARD SCOPE and a NO-NEW-MISMATCH risk.

**Item 2 — `test_08_input_and_business_validations.py`, same double-unwrap at 6 sites (6 tests).**
(a) Subject: identical plumbing defect; no behavior involved.
(b) Enumerated: read the full file. Revived assertions are PRD-verbatim: `ERR_START_BEFORE_WAVE` strictness and its equal-date acceptance, `ERR_HEADCOUNT_EXCEEDED` over `offered_count`, the permit prerequisite map, `ERR_ARRIVAL_DATE_IN_PAST` against the logical clock, `ERR_CROSS_PROGRAM_REFERENCE` winning over not-found, and the stabilization gate order `ERR_PUNCH_LIST_OPEN` → `ERR_OSE_ORDER_PENDING`. The one PRD silence these newly-running tests touch is *permissive* (impl allows punch-item, budget-line and OS&E-order creation while `schedule_state` is `SOFT_OPENING`; PRD states no state guard for those creates, so a fresh implementer reading PRD alone also adds none) — silence and impl agree, so no pin is needed.
(c) No wording adjustment — no edit.

**Item 3 — `test_13_concurrency_versioning_and_consistency.py`, removed post-`CONSTRUCTION_COMPLETE` `make_milestone` setup call.**
(a) Subject: the milestone-creation program-state guard, and the program `version` increment on each program write.
(b) Enumerated: `implementation/routes/milestones.py:22-38` (`create_milestone` — `guards.ensure_not_stabilized` then `schedule_state not in ("PLANNING","BASELINED") → ERR_INVALID_PROGRAM_STATE`), `implementation/guards.py:5-9` (`ensure_not_stabilized` also raises `ERR_INVALID_PROGRAM_STATE`, matching §3.9's "from STABILIZED nothing further may be mutated"), and the three writes the surviving assertions cover: `routes/programs.py:198` `open_booking` (+1), `:226` `suspend_booking` (+1), `:188` `recompute_schedule` (+1 via `tx.commit(program["id"])`). The impl guard is a verbatim match for PRD §3.2 ("Milestones may only be added while the program's delivery dimension is `PLANNING` or `BASELINED`… refused with `ERR_INVALID_PROGRAM_STATE`") and for §3.8's "Both variants increment the program's `version` by one."
(c) No wording adjustment — no edit. Step 7's "TEST IS WRONG" diagnosis is confirmed.

**Items 4 & 5 — no `test_helpers/` fixes, no `implementation/` fixes.** Nothing to trace, hence nothing to pin.

Incidental observation, left unpinned as out of scope: `create_milestone` accepts `code` at 1–64 chars and does not enforce the upper-snake-case shape PRD §3.2 mentions. No Step 7 item exercised milestone-code shape or length, so patching it would exceed the HARD SCOPE and risk a new mismatch.

## Step 9: Complete PRD — 2026-09-01T08:42:56.239Z

`/home/ubuntu/github/CodingPRD/tasks/task_2221_hotel_pre_opening_program_management/workspace/PRD_COMPLETED.md` exists.

## Size

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 411 | 412 (+1) |
| chars | 88,984 | 99,850 (+10,866) |

Structure untouched: 28 headings before and after, no new sections. 33 in-place paragraph revisions + 1 added bullet in §2.2.

## Counts
- **ambiguity-pins: 25**
- **mismatch-revisions: 9**

## Changes

- §2.1 — revise — ambiguity — blank/whitespace-only `X-User-ID` also yields `ERR_UNAUTHENTICATED` — `middleware.py:24`
- §2.2 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404, bad method → `ERR_METHOD_NOT_ALLOWED` 405, unparseable/non-object body → `ERR_INVALID_REQUEST`, empty body = `{}`, trailing slashes ignored — `app.py:58-70`, `validate.py:16-27`, `app.py:39`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` rejected, empty string falls back to default, bad enum filter value rejected, unmatched id filter yields empty page not 404 — `validate.py:160-189`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion sequence; test-run log ties by later `created_at` then sequence — `db.py:112`, `routes/systems.py:139-143`
- §2.4 — revise — ambiguity — `version` advances at most once per request; a no-field-change request bumps neither `version` nor `updated_at`; records created in the request stay at 1 — `db.py:76-104`
- §2.4 — revise — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from real wall clock, not the logical clock — `clock.py:32-34`, `db.py:53`, `response.py:19`
- §2.6 — revise — ambiguity — a posture recomputation with unmoved inputs writes nothing (milestone add/start, punch submit-verification, session complete/cancel) — `services/derive.py:369-393`, `routes/milestones.py:125`
- §2.6 — revise — **mismatch** — frozen brake covers **six** operations, not five: committing an OS&E order added — `routes/budget.py:110`
- §2.10 tier 3 — revise — ambiguity — optional free-text `reason` = 1–500 chars, validated then discarded (only permit `deficiency_reason` persists); `expected_*_version` are required ints ≥ 1 so bad values fail as 400 not 412 — `routes/milestones.py:160`, `routes/budget.py:98,194`, `routes/reservations.py:29`
- §2.10 tier 9 — revise — **mismatch** — "five" → "six" exposure-adding operations — `routes/budget.py:110`
- §3.1 — revise — ambiguity — creation also zeroes `schedule_slip_days`, `payroll_accrual_cents` and both cost bases; mirror `projected_opening_date` also starts null — `routes/programs.py:44-59`
- §3.1 — revise — ambiguity — `variant_gap_days` null while either projection is null; the readiness read recomputes nothing and rounds the four terms to 4dp — `routes/programs.py:137-150`
- §3.2 — revise — **mismatch** — milestone `code` is any 1–64 char string; upper snake case not enforced — `routes/milestones.py:25`
- §3.2 — revise — ambiguity — dependency graph checks ordered self-edge → duplicate → cycle; `role` filter accepts `predecessor`/`successor` case-insensitively else 400 — `routes/milestones.py:194-215,226-231`
- §3.2 — revise — ambiguity — milestone-state test precedes delivery-state test; delivery test applies only to `NOT_STARTED → IN_PROGRESS`; start triggers no schedule/counter/posture recomputation — `routes/milestones.py:111-125`
- §3.3 — revise — ambiguity — baseline test order (state → empty → cycle); recompute leaves `baselined_by_user_id` alone and is admissible from any state but `STABILIZED` — `routes/programs.py:166-195`
- §3.3 — revise — ambiguity — persisted `earliest_start_date`/`earliest_finish_date` are the `COMMITTED` forward pass; the `OPTIMISTIC` pass is never written to a milestone — `services/schedule.py:139-140`
- §3.4 — revise — ambiguity — resubmission with gating milestone in `NOT_STARTED`/`REOPENED` → `ERR_GATING_MILESTONE_NOT_COMPLETE` — `routes/permits.py:100-102`
- §3.4 — revise — ambiguity — on `DEFICIENCY`, a gating milestone in `NOT_STARTED`/`REOPENED`/`BLOCKED` absorbs review days but keeps its state — `routes/permits.py:150-153`
- §3.5 — revise — ambiguity — `executed_at` stored/echoed verbatim, may be before or after the logical clock — `routes/systems.py:93,111`
- §3.5 — revise — **mismatch** — the <0.50 demotion reads the *recomputed* `latest_pass_rate` (newest run by `executed_at`), not necessarily the just-appended run; append always bumps the system's `version` — `routes/systems.py:125-130`, `services/derive.py:46-53`
- §3.5 — revise — **mismatch** — certification duty-separation is a tier-6 check evaluated *first*, ahead of the state and threshold tests — `routes/systems.py:154-162`
- §3.6 — revise — ambiguity — offer check order: wave-start → session capacity → department → headcount — `routes/staffing.py:112-117`
- §3.6 — revise — ambiguity — `DECLINE`/`WITHDRAW` keep the hire's `orientation_session_id`; the seat frees because terminal hires drop out of `enrolled_count` — `services/derive.py:100-111`
- §3.6 — revise — ambiguity — completing/cancelling a non-`SCHEDULED` session → `ERR_INVALID_PROGRAM_STATE` 409; state test precedes end-instant/enrolment tests — `routes/staffing.py:318-322,338-342`
- §3.6 — revise — ambiguity — assign-orientation requires hire in `OFFERED`/`ACCEPTED` else `ERR_INVALID_HIRE_STATE`; capacity test excludes the hire's own seat; capacity before department — `routes/staffing.py:83-88,203-206`
- §3.7 — revise — **mismatch** — committing an order is refused while `FROZEN`, after the version guard; storage-capacity test precedes the budget test — `routes/budget.py:108-116`
- §3.7 — revise — **mismatch** — receiving is one of "six" frozen operations; frozen checked after order-state and before window — `routes/budget.py:173-180`
- §3.8 — revise — ambiguity — open-booking from `BOOKING_OPEN`/`SELLING_STABILIZED` → `ERR_INVALID_PROGRAM_STATE`; recovery imposes no delivery-state requirement; recovered blocks return to `ACCEPTED` losing the guarantee; suspend from any other state → `ERR_INVALID_PROGRAM_STATE`; neither reruns posture — `routes/programs.py:203-223,232-236`
- §3.8 — revise — ambiguity — `is_pre_opening` false while the committed projection is null and re-derived on every reconciliation (as are `room_nights`/`revenue_cents`) — `services/derive.py:143-158`
- §3.8 — revise — **mismatch** — "Three ceilings" → "Two ceilings"; the cap projection prices the new block as `ACCEPTED` and contributes 0 when not pre-opening — `routes/reservations.py:42-48`
- §3.8 — revise — ambiguity — guarantee's block-state test precedes the booking-open and frozen tests — `routes/reservations.py:97-102`
- §3.8 — revise — ambiguity — both resolutions clear `at_risk_reason`; neither is gated on commercial state or posture; neither reruns posture — `routes/reservations.py:117-129`
- §3.9 — revise — ambiguity — punch verify duty-separation is tier-6 (before the state test) but is skipped when `submitted_by_user_id` is null — `routes/punchlist.py:109-116`
- §3.9 — revise — **mismatch** — "Seven conditions" → "Eight", plus the actual evaluation order (SOD → state → frozen → permits/punch/systems/staffing → date) — `routes/programs.py:248-270`
- §3.9 — revise — **mismatch** — stabilization leaves a non-`BOOKING_OPEN` commercial dimension alone; `ACCEPTED`/`AT_RISK` blocks survive close-out keeping room-nights and exposure, so `contingency_liability_cents` does not necessarily fall to 0; no posture/schedule rerun — `routes/programs.py:302-309`, `services/derive.py:151-179`

---

## Pipeline complete

Final state: 174/174 tests passing across all 8 stability-sweep rounds (`workspace/implementation/results.{1..8}.json`); `workspace/PRD_COMPLETED.md` on disk.
