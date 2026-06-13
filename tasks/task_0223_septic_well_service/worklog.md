# Worklog — task_0223_septic_well_service

## Step 1: Create Task Directory — 2026-06-07T11:37:49.000Z

Created `tasks/task_0223_septic_well_service/` and `tasks/task_0223_septic_well_service/workspace/` (ID pre-assigned by orchestrator; index scan skipped per instructions). Scenario: Septic & Well Service. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-07T11:57:30.000Z

All three artifacts are in place with correct top-level key isolation. The generation is complete.

Generated all three scaffold artifacts for **task_0223_septic_well_service** (Expert difficulty), passing `scaffold_lint.py` with a clean verdict. Followed the skill specification only; did not look at any sibling task.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1201 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1074 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1156 lines

**Design profile:** temporal-windowing primary archetype blended with compliance/audit; flat topology (`api_prefix: ""`); peer-role RBAC; cyclic state-machine shape; immediate consistency.

**Counts:**
- **Entities:** 11 — Account, Technician, Site, Asset, ServicePlan, WorkOrder, Route, InspectionReport, PermitFiling, RepairLine, Reminder (Reminder is `common_fields:false` append-only). Every FK uses canonical `FK -> {Entity}.id` prefix and has a reverse-reachability GET.
- **State machines:** 6 — Account.standing (GOOD↔HOLD), Technician.status, WorkOrder.status (with DISPATCHED→SCHEDULED revert + cancel), WorkOrder.billing_status (parallel axis), InspectionReport.status, PermitFiling.status (cyclic REJECTED→DRAFT→SUBMITTED). Plus 1 concurrency rule (OCC on Site.version for service-plan supersede).
- **Calculations:** 6 — work_order_cost (estimate vs final tiered+surcharge), site_risk_score (provisional vs final), invoice_total (round-per-line-then-sum, order pinned), route_optimize, next_pump_due, compliance_temporal_gates (pins COOLING_OFF_HOURS=48, SITE_BUFFER_MINUTES=120). All formula-derived assert values computed in code and written as literals.
- **Validations:** 20 priority-ordered rows.
- **Endpoints:** 51 (≈30 business actions/creates + required FK-reverse GETs/reads + 1 `/_clock/set_current_utc` test-driving endpoint).
- **Errors:** 20, all triggered by ≥1 design instance and all referenced by validations/transitions.
- **Roles:** 4 — Dispatcher (opaque), FieldTech (entity_backed:Technician), ComplianceOfficer (opaque), Customer (entity_backed:Account).

**Difficulty design:** 9 rule_ids × 2 instances = **18 instances**.
**Corner design:** **29 active + 6 excluded_because stubs** across all 9 claim-extraction-guide sections. All excluded stubs cite real §1.8 instances by name; no duplicate names across the two design files.

## Step 3: Copy Shared Files — 2026-06-07T11:57:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T12:03:05.000Z

Generated `workspace/PRD.md` (279 lines) for the Septic & Well Service API.

**Sections covered:**
- **§1 Introduction** — accounts/sites/assets/plans/work-orders/routes/inspections/permits/reminders + money-compliance-scheduling consistency promise.
- **§2 Global Specs** (9 subsections): RBAC (Dispatcher, FieldTech→Technician, ComplianceOfficer, Customer→Account); §2.2 verbatim; pagination; common properties (Reminder common_fields:false → only id/created_at); derived-field reconciliation; OCC on service-plan creation; monetary precision/rounding; nested retrieval + FK resolution; explicit validation ordering.
- **§3 Business Logic** (12 subsections) — accounts/sites/assets; service plans + next_pump_due_date; work-order lifecycle; scheduling with ordered conflict checks; dual-variant cost calc; parts/invoicing/balance; pump-completion reminder cascade; inspection + provisional risk; permit filings + final risk; account-hold cascade; technician status; cross-system reads + logical clock.
- **§4** 4-column endpoint table (54 endpoints); **§5** 2-column error catalogue (20 errors).

**Hard contracts (all PASS):** Field-Name Coverage 61/61; Rule Coverage (20 error IDs, 38 enum/state values, OCC rule, all transitions, all calc constants: trip fee 9000¢, 1000-gal base tier 25¢, overage 40¢, 5000-bps emergency surcharge, defect weight 8 cap 24, 25-year/15-pt age penalty, 20 rejection penalty, 48h cooling-off, 120-min site buffer); §3 Path Purity (0 path/method tokens). §2.2 byte-identical.

**Confirmation:** did not read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-07T13:05:50.000Z

Generated complete test infrastructure for `task_0223_septic_well_service`.

### test_helpers/ (Stage 1) — 9 files
- `types.py` — entity TypedDicts (11 entities) + status/role enums. `Reminder` correctly omits `version`/`updated_at` (common_fields:false).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~50 methods).
- `api_errors.py` — `ApiErrorId` enum (20 errors) + HTTP status map.
- `assertions.py` — per-entity structural assertions; `assert_reminder` lean append-only variant.
- `factories.py` — input-field-only payload factories per entity.
- `constants.py` — cost/risk/temporal thresholds from PRD §3.5/§3.8/§3.9/§3.4.
- `test_users.py` — shared role headers + per-instance make_field_tech_headers / make_customer_headers builders for the two entity_backed roles.
- `fixtures.py` — composite multi-step setup helpers.
- `__init__.py` — barrel export.

### test_suite/ (Stage 2) — 7 files, 65 test functions
`conftest.py` + 6 domain-language test files (CRUD/validation, state machines, cost calculations, scheduling conflicts, cascades/counters, compliance/risk).

### Design-instance translation
- **Queue A (Difficulty):** all **18 instances translated**, each with ≥2 tests. 0 skipped.
- **Queue B (Corner):** all **29 non-stub instances translated** with ≥1 test. The **6 `excluded_because` stubs were NOT translated**: `cancel_completed_work_order_returns_invalid_state`, `overage_boundary_one_gallon_over_adds_tier2`, `invoice_total_round_per_line_then_sum`, `priority_state_before_account_hold`, `every_error_has_a_trigger_audit`, `account_hold_cascade_endtoend`.
- **No instances skipped for the PRD-first filter.**

### Audits passed
- Every docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` tag; all resolve to real instances.
- All 101 quoted PRD citation spans verified verbatim.
- All files compile; no scaffold/Table/§ leakage; no skip/skipif/xfail.
- 65 tests collect cleanly under pytest.

## Step 6: Generate Implementation — 2026-06-07T13:05:50.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

### Files written (13)
`start.sh`, `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory dicts, no seeding), `errors.py`, `response.py`, `auth.py`, `validation.py`, `serializers.py`, `calculations.py` (Decimal/ROUND_HALF_UP), `services.py` (cascades/recompute), `clock.py` (logical clock), `timeutil.py`.

### Endpoints: 51 implemented — every route in PRD §4 / SCAFFOLD §1.5, incl. `/_clock/set_current_utc`.

### start.sh contract confirmed
Reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`; dependency install guarded on `import flask`; storage in-memory only (no SQLite/disk); clean slate every boot.

### Verification (by impl-gen subagent)
Ran the real suite via `prd-bench-local-run --isolation per-test-server`: **64 passed, 1 failed, 0 errors** (39s). The single failure is a **test bug**: `test_04_scheduling_conflicts.py` imports `get_inspection_report` from `test_helpers`, which only exports `assert_inspection_report` — a collection-time ImportError unrelated to the implementation. `--isolation none` confirms same 64/65.

### Two notable findings
1. **DRAFT work orders survive account hold.** Implemented reconciled behavior: hold cascade cancels only SCHEDULED/DISPATCHED work orders (those on a route); a bare DRAFT order stays DRAFT so a later schedule attempt surfaces `ERR_ACCOUNT_ON_HOLD`.
2. **macOS reverse-DNS boot stall.** Patched `getfqdn` for unspecified addresses + silenced per-request logging so server is reachable in ~0.5s per reboot.

Caveat: `--start-command` must use the `cd <impl> && bash start.sh` form (pytest cwd is `test_suite/`).

## Step 7: Run Tests and Iterate — 2026-06-07T13:10:42.000Z

All 8 parallel rounds are green (65/65 passed, 0 failed, 0 errors in every round). The clean sweep condition is met; exited.

**Iterations run:** 2 full 8-round parallel sweeps (1 to diagnose, 1 to confirm the fix).

**Initial state:** 64/65 passing in every round, with exactly one test failing identically across all 8 rounds — `test_permit_submit_blocked_until_report_finalized` in `test_04_scheduling_conflicts.py`. Not flaky: a deterministic runtime `ImportError`.

**Root cause (the pre-flagged known issue):** Inside the test body, a function-scope import pulled `get_inspection_report` from `test_helpers`, which is not exported (the barrel only exposes the entity assertion `assert_inspection_report`; `get_inspection_report` exists solely as an `ApiClient` method). The import raised `ImportError` before any assertion ran. The test never needed the bogus name — line 198 already calls the correct `api.get_inspection_report(...)` ApiClient method.

**Diagnostic protocol result:** STEP 1a/1b — PRD §3.9 verbatim covers and uniquely determines the asserted rule ("The linked inspection report must be `FINALIZED`, or the submit is rejected with `ERR_REPORT_NOT_FINALIZED`"), so the test stays. STEP 2 — the failure is a test bug confined to an unused import name, fixed in `test_suite/`.

**Fixes applied:**
- `test_suite/test_04_scheduling_conflicts.py` (in `test_permit_submit_blocked_until_report_finalized`): removed the non-existent `get_inspection_report` from the function-scope `from test_helpers import (...)` line. No assertion weakened — the exact `ERR_REPORT_NOT_FINALIZED` check and the DRAFT read-back (via the valid `api.get_inspection_report(...)` method) unchanged.

**Tests deleted:** None — no PRD-silence or unique-derivability collapse present.
**Fixes to `test_helpers/`:** None.
**Fixes to `implementation/`:** None — implementation already correct; sole failure was a test-layer import bug.

**Final verification:** Re-ran the full 8-round parallel sweep — all 8 rounds 65/65 passed, 0 failed, 0 errors (orchestrator re-confirmed each results.{1..8}.json: 65/65).

## Step 8: Finalize PRD — 2026-06-07T13:12:59.000Z

PRD_FINALIZED.md created as a faithful copy of PRD.md. **No edits made.** (Step 8 run rather than skipped because Step 7 did not exit on the first sweep and had 1 test_suite fix; subagent verified the diff item traces to no PRD silence/mismatch.)

**Line counts and delta:** PRD.md = 279 lines, PRD_FINALIZED.md = 279 lines. Delta = 0 lines (0.00%). Byte-identical (orchestrator-confirmed `diff -q`: IDENTICAL).

**Justification:** The sole Step 7 diff item was a pure test-code import typo — removal of a non-existent, unused name (`get_inspection_report`) from a function-scope import in a test file. It produced 0 implementation fixes, 0 test deletions, 0 test_helpers fixes, so there is no PRD-silence or PRD/impl mismatch to pin.

**Pre-edit search log (verification → "no edits"):**
- Subject: permit-filing submit blocked until linked inspection report is FINALIZED (`ERR_REPORT_NOT_FINALIZED`), PRD §3.9.
- Impl paths: `ERR_REPORT_NOT_FINALIZED` → single site `app.py:1049` (+ status map `errors.py:32`); `permit_filing_submit` at `app.py:1037-1063` rejects when `report is None or report["status"] != "FINALIZED"` then checks `ERR_SITE_NON_COMPLIANT` / `ERR_COOLING_OFF` — matching PRD §3.9 three-condition order. `get_inspection_report` → only legit GET endpoint `app.py:912`.
- PRD §3.9 (line 174) verbatim covers and uniquely determines the rule; impl already correct. No silence, no divergence. No wording adjustment warranted.

## Step 9: Complete PRD — 2026-06-07T13:18:33.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation/ scan, starting from PRD_FINALIZED.md.

**Files:** source `PRD_FINALIZED.md` → `PRD_COMPLETED.md`. Line counts 279 → 279. Char delta 40,665 → 41,458 (**+793 chars**).

**Counts:** 3 ambiguity-pins, 3 mismatch-revisions (across 5 paragraphs; §3.6 invoice_total_cents mismatch = one logical revision spanning two adjacent sentences).

**Changes:**
- **§3.3 Work-Order Lifecycle — insert — ambiguity** — pinned `window_start_minute` must be 0–1440 inclusive else `ERR_VALIDATION` (PRD silent on range/rejection) — `app.py:457-458`
- **§3.6 Parts/Invoicing — insert — ambiguity** — pinned a repair line references its work order by FK only; system does not constrain that order's `work_type` (line on a non-`REPAIR` order accepted) — `app.py:777-807`
- **§3.6 Parts/Invoicing — revise — mismatch** — PRD said `invoice_total_cents` stays 0 until invoiced and invoicing freezes it; impl computes/freezes it at completion and merely adds to account balance at invoice (no recompute). Revised both sentences — `app.py:681` (completion freeze), `app.py:717-734` (invoice add-only)
- **§3.9 County Permit Filings — insert — ambiguity** — pinned `decision` enum to exactly `APPROVE`/`REJECT` (else `ERR_INVALID_REQUEST`); PRD only said "an approve/reject decision" — `app.py:1073`
- **§3.10 Account Holds — revise — mismatch** — PRD said hold cascade cancels `DRAFT`/`SCHEDULED`/`DISPATCHED`; impl cancels only `SCHEDULED`/`DISPATCHED`, leaves bare `DRAFT` (so a later schedule attempt surfaces `ERR_ACCOUNT_ON_HOLD`). Revised to match — `app.py:172-187`
- **§3.11 Technician Status — revise — mismatch** — PRD defined a well job as "a `WELL` asset or well inspection"; impl `_is_well_job` keys off the serviced site having any `ACTIVE` `WELL` asset, independent of `work_type`. Revised to pin site-based determination — `app.py:512-518`

**Left unchanged (PRD already pins, impl agrees):** tiered cost model + rounding (§3.5/§3.7), provisional/final risk (§3.8/§3.9), scheduling conflict ordering + 120-min site buffer (§3.4), route counters/optimize ordering (§3.4), cooling-off boundary (§3.9), reminder shape/version-less (§2.4/§3.7), response envelope, pagination, RBAC, validation ordering (§2.x).

---

## Pipeline complete — 2026-06-07T13:18:33.000Z

Final state: **65/65 tests pass across all 8 parallel stability rounds**. All 9 steps executed. Outputs present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
