# Worklog — task_2216_destination_management_company_ground_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2216_destination_management_company_ground_operations/` and its `workspace/` subdirectory (name pre-allocated by the invoking command; no index scan performed).

## Step 3: Copy shared files — 2026-09-01T02:35:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines). Executed out of order (ahead of Step 2's completion) because it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-09-01T03:35:00.000Z

(RESUME NOTE: the prior crashed run left no Step 2 artifacts on disk; Step 2 was regenerated from scratch with the verbatim scenario description.)

Scaffold for task 2216 is complete and lint-clean. Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/`):

- `SCAFFOLD.yaml` — 3175 lines, top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys leaked in)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 1568 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 3554 lines

## Counts

| Table | Count |
|---|---|
| §1.1 entities | **12** (Program, Venue, Supplier, SupplierContract, ProgramElement, Permit, TransportSegment, ManifestEntry, StaffMember, StaffAssignment, ReconciliationLine, SettlementPayment) |
| §1.2 state machines | **10** (44 transitions; Program carries two parallel dimensions — execution_status and settlement_status) |
| §1.2.1 concurrency rules | 2 (OCC-only: `expected_program_version`, `expected_contract_version` → 412) |
| §1.3 calculations | **8** (3 dual-variant, all with pinned rounding/evaluation order) |
| §1.4 validations | **49** (priority-ordered ladder) |
| §1.5 endpoints | **70** |
| §1.6 errors | **63** |
| §1.7 roles | 6 (2 entity-backed, segregation-of-duties model) |
| §1.8 instances | **19** across all 9 difficulty rules (2/3/2/2/2/2/2/2/2) |
| §1.9 instances | **82 entries = 63 recipes + 19 `excluded_because` stubs** |

This clears Expert (§0.4: 10–15 entities / 20–32 endpoints / 18–30 errors / 4+ state machines) on every axis — 70 endpoints and 63 errors are roughly double the top of the Expert band.

§1.9 per-section spread: entities 13, state_machines 13, calculations 9, validations 6, endpoints 4, errors 24, rbac 6, complexity_layers 6, consistency_model 1.

## Work done this session

Closed the error-triggerability gap flagged by `references/claim-extraction-guide.md` ("for each error in the catalog, there must be at least one test that causes it"). 28 of 63 error ids had no §1.8/§1.9 reference; I added 11 compact `section: errors` recipes covering all of them:

- `every_entity_lookup_with_an_unknown_id_returns_not_found` (9 remaining `*_NOT_FOUND` ids in one sweep)
- `element_set_mutation_after_lock_design_rejected`, `lock_design_and_confirm_on_an_element_free_program_rejected`
- `program_create_with_markup_pct_outside_the_band_rejected` (0.36/0.04 reject, 0.05 inclusive bound accepts)
- `element_create_outside_the_program_window_rejected`, `weather_alternative_pointing_at_a_fair_weather_element_rejected`
- `contract_and_element_create_for_a_prospect_supplier_rejected`, `staff_assignment_role_mismatch_and_inactive_confirm_rejected`
- `execution_sequence_preconditions_rejected` (5 error ids: NOT_CONFIRMED, WINDOW_NOT_OPEN, CHECKIN_WINDOW_NOT_OPEN, ELEMENT_NOT_STARTED, PREDECESSOR_NOT_DELIVERED)
- `reconciliation_stage_transitions_rejected` (4 ids off one line with `variance_pct` 0.25)
- `settlement_against_a_non_active_contract_and_double_void_rejected` (CONTRACT_NOT_ACTIVE at both open and approve; double void → SETTLEMENT_ALREADY_PAID)

Also fixed a formula inconsistency: `reconciliation_line_amounts` defines `variance_pct` with `abs()`, but one setup note read `(28-30)/30 = -0.0667`; corrected to `abs(28-30)/30 = 0.0667`.

Audits all pass: 0 duplicate §1.9 names, 0 overlap between §1.8 and §1.9 names, all 19 stub `difficulty_instance` citations resolve, 0 unbound `${var}` placeholders across 856 calls, 0 invalid enum literals (the one hit is the deliberate `element_type: "GALA_DINNER"` invalid-enum negative test), and **0 of 63 error ids unreferenced**.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  856

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint was respected throughout: no sibling `tasks/task_*/` directory was listed, read, or grepped — only `SCAFFOLD.yaml` and the two design files for 2216 itself, plus the skill's own spec and `scaffold_lint.py`.

Orchestrator verification: all three files parse as valid YAML; top-level keys confirmed correct (SCAFFOLD.yaml carries no design keys; each design file carries exactly its single design key).

## Step 4: Generate PRD — 2026-09-01T05:20:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/workspace/PRD.md` — **501 lines**, ending at §5 with no audit footer.

**Section list**
- `# DMC Ground Operations API — Product Requirements Document`
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination and List Filtering; 2.4 Common Resource Properties and the Logical Clock; 2.5 Optimistic Concurrency on Parent Aggregates; 2.6 Money, Head Counts and Rounding Discipline; 2.7 Cascade Depth, Derived Counters and Bubble-Up States; 2.8 Path Resolution and Reference Checking; 2.9 Order of Rejection; 2.10 Segregation of Duties on the Contracting and Payment Desks
- §3 Business Logic & Workflows — 3.1 Programme Intake and the Two Lifecycle Dimensions; 3.2 Curating the Element Set: Venues, Production Timelines and Rain Plans; 3.3 The Vendor File and the Contracting Cycle; 3.4 Permitting with the Issuing Authorities; 3.5 Ground Transportation and Manifest Management; 3.6 The Staffing Plan: Credentialing, Rest and On-Site Attribution; 3.7 On-Site Execution: Ready, Deliver, and the Weather Alternative; 3.8 Reconciliation: Actual Attendance versus Guaranteed Counts; 3.9 Client Billing, Credit Notes and Supplier Settlement
- §4 Endpoint Definitions (4-column table, 70 rows)
- §5 Error Code Catalogue (2-column table, 64 rows)

**Coverage audit**
- **§1.1 entities (12/12):** Program, Venue, Supplier, SupplierContract, ProgramElement, Permit, TransportSegment, ManifestEntry, StaffMember, StaffAssignment, ReconciliationLine, SettlementPayment — each created/read in §3 prose, all with `common_fields` documented once in §2.4.
- **§1.2 state machines (10/10 machines, 44/44 transitions):** both Program dimensions (`execution_status`, `settlement_status`) plus SupplierContract, Permit, ProgramElement, TransportSegment, ManifestEntry, StaffAssignment, ReconciliationLine, SettlementPayment. Cycles (contract `SENT`↔`COUNTERED`, permit `SUBMITTED`↔`CONDITIONS_REQUESTED`, element `PLANNED`↔`PERMIT_BLOCKED`, line `DRAFT`↔`APPROVED`, settlement `CLIENT_INVOICED`→`CREDITED`→`RECONCILING`), the manifest-move self-transition, and both bubble-up derivations (`IN_EXECUTION`→`COMPLETED`, `CLIENT_INVOICED`→`SETTLED`) are all described.
- **§1.3 calculations (8/8):** element_billable_headcount (both variants with the 110/100/70 → 110 vs 85 contrast), staff_labor_cost, reconciliation_line_amounts, program_client_total (six pinned steps, tier keyed on base), cancellation_penalty, settlement_net_payable (deposit waterfall), staff_credential_status, segment_seat_occupancy. All constants stated in words; all rounding orders pinned.
- **§1.4 validations (49/49):** every rule's error ID and condition appears in prose, and the full precedence chain is enumerated as 49 ordered bands in §2.9 with the domain rationale (compliance outranks geometry; fiscal checks last).
- **§1.5 endpoints (70/70):** every method+path pair present in §4 with description and authorized roles; the `/_clock/set_current_utc` capability included.
- **§1.6 errors (63/63):** all catalogued with correct HTTP status. One extra row, `ERR_ELEMENT_NOT_WEATHER_DEPENDENT` (409), was added because it is required by the §1.2 `READY`→`WEATHER_SWITCHED` guard but absent from the §1.6 list — documenting it gives the implementer the status code the guard needs.
- **§1.7 roles (6/6):** ProgramDirector, OperationsCoordinator, SupplierManager, Supplier, Controller, PermitOfficer, each with capabilities and its `identity:` semantics translated (StaffMember-backed, Supplier-backed, and opaque with the recorded-operator explanation feeding §2.10).

**Hard Contracts**
- Field coverage check: 138 required names (113 entity fields + request-body inputs + 12 path params + pagination + `fee_pct_applied` / `current_utc` / `to_iso8601` / common fields) — 0 missing. Status: PASS (verified on two passes).
- Rule coverage check: entities, state machines, calculations, validations, endpoints, errors, roles, concurrency rules (both OCC guards in §2.5) all represented. Status: PASS.
- Path purity check: 0 backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path. Status: PASS.

No fuzzy quantifiers, no pseudocode operators, and no content from `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task was read or referenced.

Orchestrator verification: `workspace/PRD.md` is 500 lines on disk, opens with the §1 Introduction and terminates cleanly on the final `ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE | 422` catalogue row — non-truncated.

## Step 5: Generate unit tests — 2026-09-01T06:45:00.000Z

The suite is complete and verified.

## Files created

`test_helpers/` (9 files, Stage 1 infrastructure)
`/home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/test_helpers/` — `__init__.py` (barrel re-exporting the framework validators plus every local factory/fixture), `api_client.py`, `api_errors.py` (`ApiErrorId` enum), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

`test_suite/` (22 files: `conftest.py` + 21 test modules)
`test_01_client_total_and_billable_headcount.py`, `test_02_labor_cost_calculation.py`, `test_03_state_machine_cycles.py`, `test_04_transitive_cascades.py`, `test_05_rejection_order.py`, `test_06_boundary_precision.py`, `test_07_cross_entity_gating.py`, `test_08_resource_overlap_geometry.py`, `test_09_conservation_invariants.py`, `test_10_program_and_venue_representation.py`, `test_11_entity_lookup_and_graph.py`, `test_12_state_machine_edges.py`, `test_13_calculation_inputs_and_tiers.py`, `test_14_validation_gates.py`, `test_15_endpoint_projections.py`, `test_16_settlement_refusals.py`, `test_17_transport_manifest_refusals.py`, `test_18_design_and_lookup_refusals.py`, `test_19_execution_and_settlement_ladders.py`, `test_20_role_and_identity_boundaries.py`, `test_21_concurrency_guards_and_derived_state.py`.

## Counts

- **135 tests total.**
- **Queue A (Difficulty): 51 tests**, covering **19/19** difficulty instances, every one with ≥2 tests (modules `test_01`–`test_09`).
- **Queue B (Corner): 84 tests**, covering **61/63** non-stub corner instances (43 with one test, 18 with ≥2). All 19 `excluded_because:` stubs emit nothing and resolve to real difficulty instances.

Mechanical verification (AST walk over the suite): exactly one trailing `Design:` line per test, every tag resolving to a real `rule_id`/`section`+`name` in the two design indices, every double-quoted PRD span surviving a whitespace-normalized literal substring check against `workspace/PRD.md`, no occurrence of the word "scaffold" — 0 problems. pyflakes clean, `compileall` ok.

## Instances SKIPPED (2)

1. `unlock_design_blocked_when_staff_already_confirmed` (state_machines) — `ERR_PROGRAM_ALREADY_STAFFED_ON_SITE` requires an assignment at `CHECKED_IN`/`COMPLETED`, which per §3.6 is only reachable while the programme is `IN_EXECUTION`; but at that point the unlock endpoint's own status precondition (band 8) preempts with a different code, so the PRD does not uniquely derive the asserted outcome.
2. `contract_and_element_create_for_a_prospect_supplier_rejected` (errors) — §3.3 imposes the `APPROVED` supplier requirement only on a contract **send**. `ERR_SUPPLIER_NOT_APPROVED` on contract *drafting* or element *creation* is not derivable from the PRD.

## Recipe deviations worth flagging (implemented, all PRD-grounded)

1. Seven difficulty recipes plus the corner staff-cap recipe confirm staff assignments on a `DRAFT` programme; §3.6 requires `DESIGN_LOCKED`/`CONFIRMED`/`IN_EXECUTION`, so `lock_design(...)` was inserted (or `setup_locked_program_with_segment` used).
2. `contract_negotiation_cycle_capped_at_three_rounds` is arithmetically impossible as written (only sends move `round_count`); the cap was triggered with a **counter** at `round_count == 3`.
3. `mark_ready_requires_active_supplier_contract` asserts an unreachable error at mark-ready; `ERR_NO_ACTIVE_SUPPLIER_CONTRACT` is asserted at programme confirm instead, where §3.6 places it.
4. `credential_expiring_window_inclusive_boundary_on_confirm` expected an `EXPIRING` member to be confirmable; §3.6 requires exactly `VALID`, so refusal is asserted.
5. `cancelled_program_rejects_further_transitions` — the start-execution trigger was dropped (preempted by an earlier band).
6. Two recipes (`waterfall calculation`, `derived_program_money_reconciles_after_a_line_correction`) asserted invoice-only figures (`management_fee_cents`, `final_client_total_cents`) after mere line approval; §3.8 recomputes only four figures at approval and §3.9 writes the fee/total at invoice issue, so `issue_invoice(...)` was inserted before those assertions.
7. `execution_sequence_preconditions_rejected` check-in acts as `make_operations_coordinator_headers(staff_id)` because §3.6 requires `X-User-ID == staff_id`; otherwise the test would land on `ERR_NOT_RESOURCE_OWNER` instead of the intended window error.

Note: the tests were not executed — the implementation is being generated concurrently and `workspace/implementation/` was never read.

Orchestrator verification: `test_helpers/` has 9 files, `test_suite/` has conftest.py + 21 test modules, 135 `def test_` definitions counted on disk, and `python3 -m compileall` is clean across both directories.

## Step 6: Generate implementation — 2026-09-01T06:45:00.000Z

Implementation complete and boot-verified.

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/workspace/implementation/` — 18 files, 3,427 lines total:

| File | Lines | Role |
|---|---|---|
| `app.py` | 63 | Flask app factory, blueprint registration, `ApiError`/404/405/500 handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `start.sh` | 16 | reads `$PORT` (default 8080), guarded `pip install flask`, `exec python3 app.py` in foreground |
| `requirements.txt` | 1 | `flask>=3.0.0` |
| `store.py` | 141 | in-memory `DB` (12 dicts), logical clock pinned to `2026-08-01T00:00:00Z`, time/row helpers |
| `errors.py` | 98 | 64-code catalogue → HTTP status, `ApiError`, `fail()` |
| `envelope.py` | 54 | `meta`/`response_type`/`data` envelope, `req_` + 20-char request ids, pagination meta |
| `auth.py` | 68 | header auth, six roles, `@endpoint(roles)` |
| `validation.py` | 222 | band-6 shape validators, pagination, query filters |
| `calc.py` | 189 | all 8 pinned calculations (Decimal + ROUND_HALF_UP) |
| `derive.py` | 191 | derived-on-read aggregates, governing-contract ranking |
| `cascades.py` | 153 | staff release/complete/no-show, element block/cancel, segment cancel, both bubble-ups |
| `ops.py` | 82 | line materialisation/recompute, estimate & final client totals |
| `serializers.py` | 265 | 13 serialisers |
| `common.py` | 84 | 12 `*_or_404` resolvers, list/filter helpers |
| `routes_programs.py` | 287 | clock + programme (13) |
| `routes_vendor.py` | 274 | venues, suppliers, contracts (14) |
| `routes_elements.py` | 453 | elements + permits (12) |
| `routes_transport.py` | 258 | segments + manifest entries (10) |
| `routes_staff.py` | 287 | staff members + assignments (10) |
| `routes_settlement.py` | 241 | reconciliation lines + settlement payments (10) |

## Endpoints

**70 registered routes**, exactly matching the 70 rows of PRD §4 (verified by dumping `url_map`).

## Boot and behaviour verification

Launched via `./start.sh` on ports 18216/18218, exercised with three smoke scripts, then killed (no processes or listeners remain).

- **Fresh boot is empty**: all 12 collections return `[]` with `total_count: 0`; a new programme's cost-summary reads all zeros; clock reads `2026-08-01T00:00:00.000Z`.
- **Full happy path passes end to end**: programme → venue → supplier → contract (send/countersign, deposit booked) → element → lock/confirm → staff propose/confirm/check-in → segment + manifest + curb check-in + depart → deliver (staff auto-COMPLETED, programme bubbles `IN_EXECUTION→COMPLETED`) → reconcile → patch/approve line → issue-invoice → settlement open/approve/release.
- **Calculations verified against PRD worked examples**: attrition floor `ceil(100×0.85)=85` billed vs 70 actual; `variance_pct 0.3`; per-line markup `85×9000×0.2=153000`; fee tier `base 918000 → 0.09 → fee 82620 → total 1000620`; labour `120 min → 240-min floor → 12000`; STRICT tier inside 8 days → full `15×5000=75000`; deposit waterfall `1500000 deposit vs 765000 gross → applied 765000, net 0, overpayment 735000`.
- **Error bands behave per §2.9**: `ERR_SUPPLIER_INSURANCE_INSUFFICIENT` before `ERR_SUPPLIER_NOT_APPROVED`; `ERR_CREDENTIAL_EXPIRED` (an `EXPIRING` badge is rejected) before `ERR_STAFF_INACTIVE`; capacity (31) before duplicate (32); `ERR_SEGREGATION_OF_DUTIES` last on both countersign and release; `ERR_STALE_PROGRAM_VERSION` 412; `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` at round 3; touching-end staff shifts collide while venue bookings would not; unknown route → `ERR_NOT_FOUND` 404, bad method → `ERR_METHOD_NOT_ALLOWED` 405, `limit=0` → 400.
- **Cascades verified**: weather-switch promotes the rain plan and releases shifts; contract termination cancels the supplier's open elements with the stamped penalty; segment cancellation releases the manifest and bumps `unseated_guest_count` while `seated_guest_count` falls to 0; release from `CONFIRMED` bumps `staffing_gap_count` and drops `confirmed_minutes_total` to 0; credit-invoice performs the same-request `CREDITED→RECONCILING` follow-on, clearing the fee and total while `credit_note_cents` retains 99120.

## Design decisions worth flagging

- Storage is process-local dicts only; nothing is seeded, and no file/DB/cache is written (`PYTHONDONTWRITEBYTECODE=1` in `start.sh`).
- PRD §2.9's 49-band order is applied globally and overrides SCAFFOLD's local precondition order wherever they disagree (contract send, staff confirm, manifest move).
- `created_at`/`updated_at` use wall clock; only the explicitly named stamps (`submitted_at`, `decision_at`, `delivered_at`, `check_in_at`, `completed_at`, `departed_at`, `invoice_issued_at`) read the logical clock.
- Aggregates the PRD calls "recomputed" are derived on read; only the monotonic counters (`staffing_gap_count`, `unseated_guest_count`), `credit_note_cents` and the stamped money snapshots (`estimated_client_total_cents`, `management_fee_cents`, `final_client_total_cents`, `fee_pct_applied`, `invoice_issued_at`) are stored.
- `version` is bumped only where PRD §3 or SCAFFOLD `side_effects` explicitly say so.

Orchestrator verification: 20 files present in `workspace/implementation/` including `start.sh` (reads `$PORT`, `exec python3 app.py` in foreground) and `requirements.txt`; `python3 -m compileall` clean.

## Step 7: Run tests and fix — 2026-09-01T08:10:00.000Z

Two 8-round parallel stability sweeps (`--isolation per-test-server`, 135 tests per round).

- **Iteration 1**: 129/135 in all 8 rounds — the same 6 failures every round, no flakiness.
- **Iteration 2**: **135/135 in all 8 rounds.**

No test was deleted and no assertion was weakened; all six failures were implementation bugs.

### Fixes applied to `workspace/implementation/`

| File | Function | Why |
|---|---|---|
| `store.py` | `parse_dt`, new `SuppliedInstant`/`plain_dt`/`day_end`, `fmt_dt` | A client-supplied temporal field now remembers the literal it was filed with and is echoed verbatim. PRD §2.4 pins the ISO-with-three-fractional-digits rendering for `created_at`/`updated_at` only, and §2.2 says a create/modify returns the stored resource — so `arrival_date: "2026-09-10"` reads back as `"2026-09-10"`, not `"2026-09-10T00:00:00.000Z"` (3 failures: programme dates, supplier `insurance_expires_on`, staff `badge_expires_on`). |
| `store.py` | `new_row`, `touch`, `set_clock` | `created_at`/`updated_at` are stamped from the logical clock, per §2.4's "the server does **not** read wall-clock time. It reads a **logical clock**". `set_clock` strips the supplied literal so clock-fed stamps still render canonically. |
| `routes_elements.py`, `routes_transport.py` | element/segment create window check | The inclusive upper bound now compares against `day_end(departure_date)`: a `departure_date` filed as a bare calendar date names the whole day, so an element ending 13:00 on departure day does not "fall after the programme's `departure_date`" (§3.2). The day-before-arrival and night-after-departure candidates still refuse with `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW`. |
| `routes_settlement.py` | `patch_line` | The reconciliation-window gate now precedes the DRAFT-status gate. A PATCH is not a state transition, so §2.9 band 8 does not apply to it, and §3.8 names exactly one refusal for patching outside the window: `ERR_PROGRAM_NOT_RECONCILING`. |

### Fixes applied to `test_helpers/` and `test_suite/`

None. Every fixture, factory and role-header builder was traced against the PRD sentence its test cited and found faithful.

### Orchestrator record — verbatim summary returned by the Step 7 subagent

All 8 rounds pass 135/135.

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep of 135 tests).
- Iteration 1: 129/135 in all 8 rounds — the *same* 6 failures every round, so no flakiness to chase.
- Iteration 2: **135/135 in all 8 rounds.**

**Tests deleted:** none. All six failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), and STEP 2 found the fixtures/factories/role-headers faithful — so all six were STEP 3 implementation bugs.

**Fixes applied to `test_helpers/`:** none. Each failing test's setup chain (`fixtures.setup_delivered_single_element_program`, `create_program`, `create_supplier`, `create_staff_member`, `create_program_element_payload`) was traced end-to-end against the cited PRD sentence and matched it.

**Fixes applied to `implementation/`** (all paths under `/home/ubuntu/github/CodingPRD/tasks/task_2216_destination_management_company_ground_operations/workspace/implementation/`):

1. `store.py` — `parse_dt` + new `SuppliedInstant` class, `plain_dt`, `fmt_dt`: a client-supplied temporal field now remembers the literal it was filed with and is echoed verbatim. PRD §2.4 pins the ISO-8601-with-three-fractional-digits rendering for `created_at`/`updated_at` *only*, and §2.2 says create/modify returns the stored resource — so `arrival_date: "2026-09-10"` must read back as `"2026-09-10"`, not `"2026-09-10T00:00:00.000Z"`. Fixed 3 failures (programme `arrival_date`/`departure_date`, supplier `insurance_expires_on`, staff `badge_expires_on`).
2. `store.py` — `new_row`, `touch`, `set_clock`: `created_at`/`updated_at` are stamped from the logical clock, per §2.4's "the server does **not** read wall-clock time. It reads a **logical clock**". `set_clock` strips the supplied literal so clock-fed stamps still render canonically.
3. `routes_elements.py` + `routes_transport.py` — element/segment create window check now compares the inclusive upper bound against `day_end(departure_date)`. A `departure_date` filed as a bare calendar date names the whole day, so an element ending 13:00 on departure day does not "fall after the programme's `departure_date`" (§3.2); the day-before-arrival and night-after-departure candidates still refuse with `ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW`.
4. `routes_settlement.py` — `patch_line`: the reconciliation-window gate now precedes the DRAFT-status gate. A PATCH is not a state transition, so §2.9 band 8 does not cover it, and §3.8 names exactly one refusal for patching a line outside the window: `ERR_PROGRAM_NOT_RECONCILING`.

Worklog updated with a Step 7 entry. Sweep artifacts `results.1..8.json` remain in the implementation dir; stray `__pycache__` and my per-round logs were removed.

Orchestrator verification: independently re-read all 8 `results.N.json` — every round reports `passed 135 / total 135 / failed 0`. Test count on disk is unchanged at 135, consistent with the reported 0 deletions.

## Step 8: Finalize PRD — 2026-09-01T08:30:00.000Z

Done. `PRD_FINALIZED.md` written with 5 minimal edits.

## Line counts
- `PRD.md`: 500 lines → `PRD_FINALIZED.md`: 504 lines (**+4 lines, +0.8%**)

## Changes
- **§2.4 — insert** — new paragraph pinning that `created_at`/`updated_at` are stamped from the logical clock (not real time), that `api_request_timestamp` is the sole real-time read, and that rows sharing a `created_at` are ranked by creation sequence wherever `created_at` orders or breaks a tie — `store.py:183` (`new_row`), `store.py:197` (`touch`), `store.py:204` (`sort_rows`), `envelope.py:17`
- **§2.4 — insert** — new paragraph pinning that a client-supplied temporal body field is stored and read back as the literal filed (whitespace trimmed, not re-rendered), naming the eleven such fields, plus the interpretation rules for comparison (no zone ⇒ UTC; bare `YYYY-MM-DD` ⇒ midnight beginning the day, unless a rule says otherwise) — `store.py:89-133` (`fmt_dt`, `parse_dt`, `SuppliedInstant`), `serializers.py:31,93,130,168,198,219`
- **§2.4 — revise** — `current_utc` is echoed in the canonical three-fractional-digit form whatever literal was supplied (the clock strips the literal) — `store.py:44-49` (`set_clock`), `routes_programs.py:37`
- **§2.9 band 8 — revise** — a `PATCH` requests no transition, so a `PATCH`'s own source-status requirement is evaluated after the phase/window bands, not at band 8 — `routes_settlement.py:66-71`
- **§3.2 — revise** — the containment upper bound is "the last instant the `departure_date` names": a bare calendar date names the whole day (an `ends_at` at 13:00 on the departure day passes; the following midnight does not), a full instant is itself the bound; the segment rule references the same bound — `routes_elements.py:146`, `routes_transport.py:75`, `store.py:136-145` (`day_end`)
- **§3.8 — revise** — the reconciliation-window gate on a line patch precedes the line's `DRAFT` gate, with both resulting error codes spelled out — `routes_settlement.py:63-71`

## Per-edit pre-edit search log

**Edit 1 (clock-fed stamps + `created_at` tie-break).** (a) Subject: source of `created_at`/`updated_at` and consequences of collisions. (b) Enumerated: `store.py` `new_row`/`touch`/`clock_now`/`sort_rows`; every `fmt_dt(row["created_at"/"updated_at"])` in `serializers.py:_common`; `envelope.py:_meta` (`utcnow` — the only real-time read in the tree, confirmed by grep for `utcnow`); every `created_at` sort site — `common.py:respond_list`→`sort_rows` (all 13 list endpoints), `routes_elements.py:325` (weather-alternative tie-break, ascending), `ops.py:33` (line materialisation, ascending), `routes_settlement.py:117-119` (waterfall order, ascending), `derive.py:181-183` (`governing_contract`, **descending** `created_at` and `_seq`). (c) Wording adjusted to be direction-neutral — "two rows sharing it are ranked by the sequence in which they were created, the row created later counting as the later of the two" — rather than "ordered by insertion order ascending", which would have mis-described `governing_contract`'s descending rank.

**Edit 2 (verbatim echo of supplied literals).** (a) Subject: rendering of every temporal field. (b) Enumerated all 24 `fmt_dt` call sites in `serializers.py` and classified each: server-stamped (`created_at`, `updated_at`, `submitted_at`, `decision_at`, `delivered_at`, `departed_at`, `check_in_at`, `completed_at`, `invoice_issued_at`) all flow from `clock_now()`, which `set_clock` keeps literal-free via `plain_dt`, so they render canonically; client-supplied (`arrival_date`, `departure_date`, `insurance_expires_on`, element/assignment `starts_at`/`ends_at`, `depart_at`, `arrive_at`, `badge_expires_on`, `first_aid_expires_on`) carry `raw`. Also checked the re-supply paths (`patch_supplier:93`, `patch_staff_member:63-65`) which re-store a fresh literal. (c) Scoped the sentence to fields "arriving in a request body" and enumerated them explicitly, so it cannot be read as covering `current_utc` (re-rendered) or the server stamps; added the "unless a rule says otherwise" hedge on bare-date interpretation so it does not contradict the `day_end` upper bound of §3.2.

**Edit 3 (`current_utc` canonical).** (a) Subject: clock-set response rendering. (b) `store.py:44-49` (`set_clock` → `plain_dt`), `routes_programs.py:31-37`, `store.py:89-106` (`fmt_dt` raw branch). (c) None.

**Edit 4 (§2.9 band 8 / PATCH).** (a) Subject: where a PATCH's source-status requirement sits in the rejection order. (b) All four PATCH handlers: `routes_settlement.py:51-81` (window then DRAFT), `routes_vendor.py:87-103` (no status gate), `routes_staff.py:57-76` (no status gate), `routes_elements.py:201-249` (design-lock gate at band 9, no source-status gate). Also every POST transition that pairs band 8 with a window/phase band, to confirm they still follow the written order: `approve_line:88-93` (DRAFT then RECONCILING), `approve_payment:192-198`, `cancel_element:345-350`, `credit_invoice:262-268`, `counter_contract:213-222`. (c) Restricted the clause to `PATCH` so the POST transitions above (which do check status first) remain correctly described; said "after the programme phase and window bands below" rather than naming a single band, since only `patch_line` exercises it.

**Edit 5 (§3.2 window bound).** (a) Subject: programme-window containment bound. (b) `routes_elements.py:146`, `routes_transport.py:75` (the two `day_end` callsites), `store.py:136-145`; grepped `departure_date` across the tree — no other reader; confirmed the lower bound (`starts_at < arrival_date`, `depart_at < arrival_date`) uses the raw literal, as does `start_execution` (`routes_programs.py:177`), and that `patch_element` never re-checks the window. Also confirmed `day_end` is *not* applied to `insurance_expires_on` (`routes_vendor.py:129`) or to credential expiry (`calc.py:182-189`). (c) Left the `arrival_date` half of the sentence verbatim and confined the new prose to the upper bound, so the edit cannot be read as widening the lower bound or the insurance/credential comparisons to whole-day semantics.

**Edit 6 (§3.8 patch order).** (a) Subject: `patch_line` gate order. (b) `routes_settlement.py:53-81` (body validation at bands 6 → window → DRAFT), `approve_line:86-102` for contrast, `ops.recompute_line` for the recompute the paragraph already describes. (c) Named both outcomes explicitly (`ERR_PROGRAM_NOT_RECONCILING` outside the window regardless of line status; `ERR_INVALID_STATE_TRANSITION` for an `APPROVED` line inside it) so the reversed order is unambiguous without implying anything about `approve`.

Orchestrator verification: `workspace/PRD_FINALIZED.md` is 504 lines on disk against PRD.md's 500; `diff` reports 12 changed lines total, confirming a genuinely minimal patch; the file terminates cleanly on the final error-catalogue row.

## Step 9: Complete PRD — 2026-09-01T08:55:00.000Z

26 line-level revisions, all in-paragraph, no structural change. `PRD_COMPLETED.md` is written.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (504 lines, 93,233 chars) → `workspace/PRD_COMPLETED.md` (504 lines, 98,940 chars); **+5,707 chars**, 26 lines revised, 0 lines added/removed, no new sections.

**Counts:** 20 ambiguity-pins, 6 mismatch-revisions.

### Changes

- §2.2 Success Response — insert — ambiguity — `cancel_reason`/`termination_note`/`release_reason`/`void_reason`/`credit_reason` are validated but never persisted or echoed; only `conditions_note` is stored — `routes_programs.py:189,259`, `routes_elements.py:344`, `routes_staff.py:281`, `routes_settlement.py:237`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST`; `total_count` counted post-filter; `has_more` = `offset + len(page) < total_count` — `validation.py:196-206`, `envelope.py:39`
- §2.3 List Filtering — insert — ambiguity — enum filters reject out-of-enum values with `ERR_INVALID_REQUEST`; id filters accept any string — `validation.py:211-218`
- §2.4 `version` bullet — insert — ambiguity — read-time-derived changes do not bump the exposing row's `version` (manifest writes leave segment/programme alone; line approval leaves programme alone), while a no-op `PATCH` still bumps it — `serializers.py:172`, `routes_settlement.py:80,101`
- §2.7 monotonic counters — insert — ambiguity — `staffing_gap_count`/`unseated_guest_count` are written without touching the programme's `updated_at`/`version` — `cascades.py:22,58,150`
- §2.7 recomputed aggregates — revise — mismatch — "every `_cents` aggregate is recomputed" was wrong; pinned the five live-derived money fields vs. the stamped snapshots (`estimated_client_total_cents`, `management_fee_cents`, `final_client_total_cents`, `fee_pct_applied`, `credit_note_cents`) — `derive.py:119-137`, `serializers.py:40-48`
- §2.8 Path Resolution — insert — ambiguity — `ERR_NOT_FOUND`/404 for undefined paths, `ERR_METHOD_NOT_ALLOWED`/405, both pre-auth; empty body read as `{}`, unparseable body 400 — `app.py:41-47`, `validation.py:18-26`
- §3.1 programme create — insert — ambiguity — `fee_pct_applied` starts at 0 — `routes_programs.py:73`
- §3.1 start-execution — revise — mismatch — source-state test (`ERR_PROGRAM_NOT_CONFIRMED`) runs *before* the window test — `routes_programs.py:174-179`
- §3.1 programme cancel — insert — ambiguity — status set to `CANCELLED` before the cascade, so no `COMPLETED` bubble-up; elements prong before transport prong — `routes_programs.py:200-204`
- §3.2 venue capacity — revise — mismatch — `ACTIVE` check runs first; `TRANSFER_BLOCK` with a venue is compared against neither capacity — `routes_elements.py:83-93`
- §3.2 element reshape — insert — ambiguity — no venue-geometry, capacity or window recheck on `PATCH`; null clears a graph edge, omission preserves it — `routes_elements.py:201-249`
- §3.3 counter-offer — insert — ambiguity — `countered_value_cents` required, min 1; `round_count` untouched by a counter — `routes_vendor.py:217,224-226`
- §3.3 terminate — insert — ambiguity — cascaded element cancellations re-evaluate the `COMPLETED` bubble-up — `routes_vendor.py:272` → `cascades.py:112,122`
- §3.4 permit open — insert — ambiguity — no element-status requirement at open — `routes_elements.py:360-379`
- §3.4 lead time — insert — ambiguity — the day count floors (not truncates toward zero), so a started element fails even `lead_time_days_required` 0 — `store.py:158-165`
- §3.5 manifest move — revise — mismatch — real order is `ERR_INVALID_REQUEST` → entry/source/target state → three manifest gates → `ERR_SEGMENT_PROGRAM_MISMATCH` (PRD had the mismatch check before the gates) — `routes_transport.py:214-232`
- §3.6 proposal — insert — ambiguity — no programme-phase check and no element/segment status check at proposal — `routes_staff.py:104-166`
- §3.6 confirmation — revise — mismatch — `ERR_CREDENTIAL_EXPIRED` precedes `ERR_STAFF_INACTIVE`, and `ERR_STAFF_ROLE_MISMATCH` runs *after* the three scheduling tests (PRD had both the other way) — `routes_staff.py:218-243`
- §3.7 weather switch — insert — ambiguity — the four gates run in the order given, weather-dependence ahead of programme phase (§2.9 does not band it) — `routes_elements.py:311-329`
- §3.7 weather switch release — revise — mismatch — `staffing_gap_count` rises only when the released shift was `CONFIRMED`, not for `PROPOSED` — `cascades.py:14-23`
- §3.7 element cancel release — revise — mismatch — same asymmetry scoping — `cascades.py:14-23`
- §3.8 line patch — insert — ambiguity — null `variance_reason` clears it; null `actual_headcount` is ignored and triggers no recompute — `routes_settlement.py:56-79`
- §3.9 issue-invoice — insert — ambiguity — the write set includes `fee_pct_applied` — `routes_programs.py:250`
- §3.9 estimate variant — insert — ambiguity — writes nothing to `fee_pct_applied` — `routes_programs.py:164-165`
- §3.9 credit reversion — insert — ambiguity — `fee_pct_applied` is reset to 0 — `routes_programs.py:283`
- §3.9 open settlement payment — insert — ambiguity — no `settlement_status` and no contract-`status` gate at creation; all posture tests sit at approval — `routes_settlement.py:124-167`
- §3.9 deposit waterfall — revise — ambiguity — group tie-break is the *line's* own `created_at` — `routes_settlement.py:114-121`

**Notable pre-existing PRD self-contradictions resolved in favour of implementation:** §3.5's move-ordering prose and §3.6's confirm-ordering prose both conflicted with §2.9's band table; implementation follows the band table, so the prose was revised rather than the table.

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 504 lines / 98,940 chars on disk and terminates cleanly on the final error-catalogue row. Steps 8 and 9 wrote no code — newest mtime under `workspace/implementation/` is 06:51 and under `test_suite/`/`test_helpers/` is 06:35, both from Step 7, whereas Steps 8–9 ran after 08:00. The 8-round green sweep (`results.1..8.json`, 135/135 each) therefore still describes the code as it stands at pipeline exit.

---

# PIPELINE COMPLETE — all 9 steps done, 135/135 tests green across 8 parallel isolation rounds.
