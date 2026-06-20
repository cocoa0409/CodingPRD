# Worklog — task_0403_non_medical_in_home_senior_care

Scenario: Non-Medical In-Home Senior Care (Home Instead style): caregiver registry & background tier, client care plan & ADL/IADL task list, visit scheduling & electronic visit verification (EVV), caregiver-client matching & continuity, hourly/live-in billing & overtime, mileage & companion errands, telephony clock-in/out, long-term-care insurance claim assignment

Difficulty: Expert (applied at Step 2 scaffold generation only).

## Step 1: Create task directory — 2026-06-18T02:58:31.000Z

Created `tasks/task_0403_non_medical_in_home_senior_care/` and `tasks/task_0403_non_medical_in_home_senior_care/workspace/`. Directory fixed per orchestration instructions (no auto-increment). Verified `./INSTRUCTION.md` and `./skills/` exist.

## Step 2: Generate scaffold (Expert) — 2026-06-18T03:39:07.000Z

All three scaffold artifacts written and pass `scaffold_lint.py` clean (`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`).

Counts (Expert tier): Entities 10 (band 10–15 ✅); Endpoints 40 (band 20–32 ⚠️ over — see note); Validations 18 (band 18–30 ✅); Calculations 5 (3+ ✅); State machines 5 (4+ ✅); Error codes 30 (18–30 ✅); Concurrency rules 1 (OCC on Invoice.version).

Design files: §1.8 has all 9 difficulty rules × 2 instances = 18 instances; §1.9 has 9 sections with 31 active + 2 `excluded_because` stub instances. 567 recipe calls scanned, all conforming. Pinned numeric assertions: overtime reconciliation 1380→1470, mileage per-entry rounding 3.06, claim percentage-vs-cap 192/150, EVV 7.5-min boundary 0/15, live-in 500.00, continuity scores 0.40/0.80.

Domain: Ledger-reconciliation + temporal-windowing — caregiver registry/background tier (parallel `background_tier × employment_status`), client care plans with ADL/IADL tasks, EVV telephony clock-in/out, caregiver–client matching/continuity (parallel `match_status × continuity_status`), provisional-vs-final overtime billing, mileage/companion errands, LTC claim assignment with OCC.

Note on endpoints (40 vs 32): the one quota outside its band. Subagent confirmed via FK reverse-reachability lint gate that a 10-entity model has a hard floor of ~38 endpoints (16 FK-mandated GETs + 10 creates + 12 state-transition actions + 1 DELETE + 1 test-clock). Reaching ≤32 would require dropping below the 10-entity Expert floor or breaking FK reachability (a hard lint gate). Prioritized harder gates (entity-count floor, FK-reachability, 9 difficulty rules, error band) per §0.4's "density, not volume" principle where endpoint range is a guideline. Remaining surface is mechanical CRUD/discovery, not added difficulty.

## Step 3: Copy INSTRUCTION.md — 2026-06-18T03:39:07.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T03:45:04.000Z

PRD written to `workspace/PRD.md` (294 lines). Design files (DIFFICULTY/CORNER) withheld per contract.

Sections covered:
- Entities (10): Agency, Caregiver, Client, CarePlan, CareTask, CaregiverMatch, Visit, MileageEntry, Invoice, LtcClaim — common fields (id/created_at/updated_at/version) in §2.4.
- State machines (6 as rendered): Caregiver (parallel background_tier × employment_status), CaregiverMatch (match_status × continuity_status), Visit (cyclic SCHEDULED/EN_ROUTE/IN_PROGRESS with revert loops), Invoice (DRAFT↔DISPUTED cycle), LtcClaim (DENIED→APPEALED→SUBMITTED loop), plus system-driven APPROVED→PAID.
- Calculations (5): provisional visit charge (forward/isolated, EVV round-half-up to evv_rounding_minutes, hourly vs live-in started-day blocks), final chronological invoice labor with overtime allocation, per-entry mileage rounding then sum, claim covered_amount (min of percentage vs daily-benefit cap), weighted continuity_score (0.6 continuity ratio + 0.4 reliability).
- Validations (18): precedence tiers in §2.6 + referential/temporal/fiscal/concurrency checks each paired with error ID.
- Endpoints (40): 4-column table incl. `/_clock/set_current_utc` test capability.
- Errors (30): 2-column catalogue; every error ID also in §2/§3 narrative.
- Roles (4): AgencyAdmin, Scheduler, Caregiver (entity-backed), BillingClerk.

Hard Contract Reports: Field coverage PASS (62/62), Rule coverage PASS, Path purity PASS (0 path tokens in §3). §2.2 emitted verbatim canonical source.

## Step 5: Generate unit tests — 2026-06-18T04:01:49.000Z

Generated complete test infrastructure (launched concurrently with Step 6).

Files: test_helpers/ (9 files): __init__.py, types.py (10 entity TypedDicts + 14 status enums + UserRole), api_client.py (38 endpoint methods), api_errors.py (30 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque AgencyAdmin/Scheduler/BillingClerk + entity-backed Caregiver builder), fixtures.py. test_suite/ (8 files): conftest.py + test_01–test_07.

Test counts: 67 tests total.
- Queue A (Difficulty): 36 tests, all 18 instances across 9 rules, 2 tests each (test_01–test_04).
- Queue B (Corner): 31 tests, all 31 non-stub instances, 1 test each (test_05–test_07).

Skipped: 0 instances. Both `excluded_because:` corner stubs correctly not translated (claim_submit_invoice_not_issued → owned by dual_variant_calc/claim_covered_percentage_vs_cap; clockout_immediately_reflects_charge_and_score → owned by boundary_precision_check/evv_rounding_half_increment_boundary).

PRD-first adjudication: corner instances create_caregiver_returns_pending_applicant_defaults and system_fields_generated_on_create each listed a `version == 1` sub-assertion; PRD §2.4 says "version begins at the value assigned on creation" but never pins initial value to 1, so dropped only that ambiguous sub-claim and kept uniquely-derivable assertions (background_tier=PENDING, employment_status=APPLICANT, max_weekly_hours=50, status=INTAKE, continuity_score=0).

Verification: all files compile; every test_helpers import resolves; all 67 docstrings carry exactly one verbatim Design: tag resolving to a real instance; no skip/skipif/xfail; no scaffold leakage.

## Step 6: Generate implementation — 2026-06-18T04:01:49.000Z

Built Python + Flask REST API at workspace/implementation/ (launched concurrently with Step 5).

Files: start.sh, requirements.txt (Flask==3.0.3), app.py, db.py (in-memory store + common-field stamping), errors.py, response.py, middleware.py (auth + RBAC), money.py (Decimal round-half-up), clock.py (logical clock + ISO helpers), services/ (lookup.py, requtil.py, calc.py, scheduling.py), routes/ (agencies, caregivers, clients, care_plans, matches, visits, invoices, claims, clock_admin).

Stack: Python 3 + Flask only. start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`; pip install guarded behind import check so per-test reboots skip install. Storage in-memory only (one dict per entity keyed by UUID); no SQLite, no disk, no seeded data; every collection empty on boot.

PRD ambiguities resolved by impl: (1) Client DISCHARGE allowed from any status except already-DISCHARGED (→ERR_INVALID_STATE). (2) MARK_PAID blocks on any attached claim not in {APPROVED, PAID}. (3) ERR_NO_BILLABLE_VISITS detected by checking finalize produced any REGULAR/OVERTIME/LIVE_IN line. (4) Added hidden monotonic _seq as final deterministic tiebreaker for created_at/clock_in_at ASC ordering (never exposed).

## Step 7: Test + iterate to green — 2026-06-18T04:04:30.000Z

Iterations run: 1 (the initial 8-round parallel stability sweep).

Result: All 8 concurrent rounds passed cleanly — `passed == total == 67` in every round, `failed=0, errors=0, skipped=0`. No flakiness surfaced across the concurrent 8× sweep. Verified independently by orchestrator: results.1..8.json all 67/67.

Tests deleted: None. No test failed in any round, so STEP 1 (PRD coverage / unique-derivability) was never triggered.
Fixes applied to test_helpers/: None required.
Fixes applied to implementation/: None required.

The implementation passes the full 67-test suite (test_01–test_07) under --isolation per-test-server with 8× concurrent load, confirming correctness and absence of timing-sensitive/port-collision flakiness.

## Step 8: Finalize PRD — SKIPPED — 2026-06-18T04:04:30.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — zero iterations beyond baseline. PRD.md already determined every behavior the implementation exhibits; no PRD_FINALIZED.md produced. Step 9 still runs (always).

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-18T04:08:46.000Z

Produced workspace/PRD_COMPLETED.md from PRD.md (PRD_FINALIZED.md absent — Step 8 skipped). Full PRD-vs-implementation scan.

Source vs completed: both 294 lines (all edits in-paragraph, no new lines/sections). Char delta 46,614 → 47,585 (+971).
Counts: 4 ambiguity-pins, 1 mismatch-revision (5 edits total).

Per-change:
- §3.3 (Client lifecycle) — insert — ambiguity — DISCHARGE allowed from any non-terminal status (INTAKE/ACTIVE/ON_HOLD); only fails ERR_INVALID_STATE when already DISCHARGED (routes/clients.py:84-87).
- §3.6 (Clocking in) — insert — ambiguity — evv_source stored as null at clock-in when not supplied; each evv_log entry records evv_source/caller_id exactly as supplied on that event, possibly null (routes/visits.py:140-146).
- §3.6 (Clocking out) — insert — ambiguity — clock-out overwrites visit's evv_source only when a non-null value is supplied; otherwise visit retains clock-in evv_source (routes/visits.py:172-179).
- §3.9 (Finalize gate) — revise — mismatch — ERR_NO_BILLABLE_VISITS precondition changed from "at least one COMPLETED visit" to "at least one COMPLETED visit that yields a labor line" (LIVE_IN always, or HOURLY with positive billable_minutes); COMPLETED HOURLY visit rounding to 0 billable minutes produces no line (services/calc.py:115-157 + routes/invoices.py:96-98).
- §3.9 (Invoice lines) — insert — ambiguity — pinned LIVE_IN line hours(0)/rate(live_in_day_rate), MILEAGE line source_visit_id(entry visit_id)/amount(line_charge)/rate(mileage_rate)/hours(0) (services/calc.py:120-126,169-175).

Left unchanged (deliberate): §2.1 general ownership principle (system-wide, no endpoint triggers it); covered-amount final rounding (covered by §2.8 blanket 2-dp round-half-up); harmless list-filter query superset; REGULAR/OVERTIME line numeric typing (non-load-bearing, tests assert via pytest.approx).

## PIPELINE COMPLETE — 2026-06-18T04:08:46.000Z

Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (8 files), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}. PRD_FINALIZED.md intentionally absent (Step 8 skipped). Final 8-round stability sweep: 67/67 pass in all 8 rounds.
