# Worklog — task_1086_multifamily_amenity_resident_experience

## Step 1: Create task directory — 2026-07-22T11:10:00.000Z

Created `tasks/task_1086_multifamily_amenity_resident_experience/` and `workspace/` (pre-assigned folder; Step 1 auto-index scan skipped by instruction).

## Step 2: Generate scaffold — 2026-07-22T11:36:00.000Z

All three artifacts complete, parse cleanly, pass `scaffold_lint.py` (VERDICT: clean lint). All 9 difficulty rules carry 2 instances each (18 total); corner stubs cite real §1.8 instances.

**Complexity profile:** primary `temporal_windowing` + secondary `posture_driven_gating`; layers = OCC, cascading side-effects, dual-variant calc, rate/threshold triggers, derived-field reconciliation; hybrid topology; cyclic state machines; segregation-of-duties role model.

**Scale**
- Entities: 14 (Property, Unit, Resident, Amenity, AmenityBooking, CommunityEvent, EventRegistration, Vendor, ServiceRequest, LedgerEntry, Package, GuestPass, Survey, SurveyResponse)
- Endpoints: 70 (all 8 scenario domains + `/_clock/set_current_utc` test-driver defaulting to `2026-05-01T00:00:00Z`; reporting via `/properties/{id}/report` and `/residents/{id}/retention`)
- Errors: 31; Roles: 4 (PropertyManager `opaque`, Resident `entity_backed`, Vendor `entity_backed`, FrontDesk `opaque`)

**State machines (8):** Resident posture (GOOD_STANDING↔DELINQUENT↔SUSPENDED), AmenityBooking (CONFIRMED↔SUSPENDED cycle + branches), ServiceRequest (TRIAGED↔ASSIGNED cycle), CommunityEvent, EventRegistration (reserved/waitlist), Package, GuestPass, Survey.

**Calculations (9):** `booking_charge` (dual-variant provisional/final, combinatorial mode-a: peak/tier/min-cap), `service_invoice` (dual-variant estimate/actual, combinatorial mode-b: per-line rounding-then-sum), `late_cancel_penalty` (threshold/boundary), `event_capacity_allocation` (boundary), `account_status_evaluation`, `payment_allocation` (waterfall), `retention_score` (weighted), `ledger_balance_reconciliation` + `amenity_slot_occupancy` (two compensating-invariant conserved quantities: money vs slot-count).

**Concurrency:** one OCC rule — `booking-create-stale-amenity` on `Amenity.version` (`POST /amenity-bookings` requires `expected_amenity_version`, bumps version).

**Difficulty design:** 18 instances (2/rule) with executable `setup_api_calls` chains + pre-computed literal asserts (booking provisional 9600 vs final 4800; service estimate 18014 vs actual 14154; late-cancel-at-exactly-24h penalty 0). **Corner design:** 21 breadth instances + 5 `excluded_because` stubs.

**Notes**
- All formula constants declared in `calculations[].constants` (tier discount 0.20, fee cap 20000, material tax 0.07, emergency trip fee 7500, late-cancel window 24h/forfeit 0.50, delinquency 50000/suspension 150000, retention weights). Amenity peak window/multiplier and buffer are per-entity input fields.
- Dropped `ERR_AMENITY_CAPACITY_EXCEEDED` (unreachable — buffer-overlap at priority 10 always precedes it); amenity concurrency folds into `ERR_BOOKING_OVERLAP`.
- `api_prefix` is empty (`""`); resources are flat top-level collections.

## Step 3: Copy INSTRUCTION.md — 2026-07-22T11:36:30.000Z

`cp INSTRUCTION.md workspace/INSTRUCTION.md`. All three scaffold YAMLs verified with `yaml.safe_load` (YAML OK).

## Step 4: Generate PRD — 2026-07-22T11:44:00.000Z

Generated `workspace/PRD.md`. §1 Intro / §2 Global (9 subsections) / §3 Business Logic (7 subsections) / §4 Endpoint table (71 endpoints) / §5 Error table (32 error IDs).

**Calculations documented (8):** booking_charge (dual-variant provisional/final, tiered peak + PREMIUM 20% discount + 20000-cap), service_invoice (dual-variant estimate/actual, per-line 7% tax + 7500 emergency trip fee, round-per-line-then-sum), late_cancel_penalty (24h inclusive boundary, 50% forfeit), event_capacity_allocation (strict `<`), account_status_evaluation (50000/150000), payment_allocation (rent-then-wallet waterfall), retention_score (weighted 0–100, 90-day window), + conservation invariants ledger_balance_reconciliation & amenity_slot_occupancy.

Coverage: OCC on POST /amenity-bookings (expected_amenity_version → ERR_STALE_VERSION 412); SoD on invoice approval; delinquency & reverse booking cascades (CONFIRMED↔SUSPENDED); TRIAGED↔ASSIGNED cycle; waitlist promotion by created_at ASC; event-cancel refund cascade; LedgerEntry/SurveyResponse are id+created_at-only. Hard Contracts 1/2/3 all PASS; all 32 error IDs surface in narrative.

**Undeclared-constant adjudication (orchestrator):** `CHECK_IN_GRACE_MINUTES` and `PACKAGE_HOLD_DAYS` are named in SCAFFOLD state-machine preconditions but carry no declared value. Verified neither appears in DIFFICULTY or CORNER design files. The check-in test instances set clock == start_at (grace non-determinative for any non-negative value); the package-return transition is not exercised by any instance. → No test skips, no boundary depends on their value; left under-determined in PRD (expressed by name). No SCAFFOLD/PRD patch. Step 9 will pin whatever impl chooses.

## Step 5: Generate unit tests — 2026-07-22T12:00:00.000Z

**test_helpers/** (9 files): types.py (12 managed-field entities + 2 immutable records LedgerEntry/SurveyResponse omitting updated_at/version), api_client.py, api_errors.py (33 error IDs), assertions.py, factories.py, constants.py, test_users.py (Resident/Vendor entity-backed + PM/FrontDesk opaque), fixtures.py, __init__.py.

**test_suite/**: 14 test files, **56 test functions**, conftest bridge.

Coverage: Queue A (Difficulty) 18/18 instances × 2 tests = 36. Queue B (Corner) 20/21 non-stub × 1 = 20. 5 `excluded_because` stubs correctly not translated.

**Skipped (1 corner instance):** `Corner/endpoints/event_amenity_wrong_property_returns_422` — failed unique-derivability. Recipe asserts ERR_PROPERTY_MISMATCH (422) at event *creation*, but PRD §3.4 attaches the check to *publishing*; a faithful reader could enforce it only at publish → test would fail. Left as gap (not weakened/xfail).

## Step 6: Generate implementation — 2026-07-22T12:00:30.000Z

**implementation/**: app.py (~1450 lines: store, logical clock, envelope, auth/RBAC, calculations, state machines, cascades, 70 routes), requirements.txt (flask==3.0.3), start.sh (foreground, $PORT default 10000, binds 0.0.0.0, guarded pip install, exec python3 app.py). Module-level dicts only; nothing seeded. Verified end-to-end against a running server (fees, OCC, cascades, waterfall, waitlist, service invoice, SoD, retention).

**PRD ambiguities resolved (candidates for Step 8/9 pinning):**
1. CHECK_IN_GRACE_MINUTES → 15; PACKAGE_HOLD_DAYS → 7.
2. Booking against non-OPEN amenity → ERR_INVALID_STATE (409), at state-priority slot before posture/temporal.
3. ERR_NOT_RESOURCE_OWNER enforced on entity-backed mutations only, not GET reads (validations priority-5 applies_to mutations).
4. Too-early booking/guest-pass check-in + package return before hold elapses → ERR_INVALID_STATE (409).
5. Guest-pass span > guest_window_hours → ERR_VALIDATION (422), after posture, before concurrency.
6. Resident email + unit_number-within-property uniqueness → ERR_VALIDATION (422).
7. rent_balance_cents/wallet_credit_cents stored incrementally-updated; wallet not auto-consumed on charges; ledger max(0,sum) invariant.
8. Resident cancels service request only from SUBMITTED; manager from SUBMITTED/TRIAGED/ASSIGNED.
9. avg_retention_score (report) rounded half-up to integer.
10. created_at wall-clock microsecond + monotonic seq tiebreak for ordering; logical-time fields use logical clock.

## Step 7: Run tests and iterate — 2026-07-22T12:10:00.000Z

**Iterations run:** 1 (single 8-round parallel stability sweep, run as 2 waves of 4).

**Result: CLEAN FIRST-SWEEP PASS.** All 8 rounds passed 56/56 (passed==total, failed==0, errors==0, skipped==0). No flakiness across the union. Orchestrator independently re-verified all 8 results.{1..8}.json: every round 56/56/0/0/0.

**Tests deleted:** None. **Fixes to test_helpers/:** None. **Fixes to implementation/:** None.

The implementation already satisfies the full 56-test suite deterministically.

## Step 8: Finalize PRD — SKIPPED — 2026-07-22T12:10:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the tested sites. No PRD_FINALIZED.md produced. Step 9 runs from PRD.md.

## Step 9: Complete PRD — 2026-07-22T12:18:00.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation scan). PRD.md 318 lines/46,645 chars → PRD_COMPLETED.md 318 lines/49,254 chars (+2,609 chars). All 15 edits in-paragraph; no new sections.

**Counts:** 13 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.1 RBAC — insert — GET reads perform no ownership check; ownership enforced only on entity-backed mutations/actions (app.py:937,731,1385 vs 899,1007,1367).
- §2.4 Identity/Timestamps — revise — mismatch — created_at is real wall-clock UTC (not logical clock); monotonic creation sequence (not id) breaks ties (app.py:282,340).
- §2.6 Ledger/Balance — insert — charges never draw down wallet_credit_cents; wallet never auto-consumed (app.py:406-408).
- §2.9 Nested Resolution — insert — GET /survey-responses/{id} non-existent → ERR_SURVEY_NOT_FOUND (app.py:1865).
- §3.1 Units — insert — duplicate unit_number within property → ERR_VALIDATION 422 (app.py:664-666).
- §3.1 Residents — insert — duplicate resident email → ERR_VALIDATION 422 (app.py:710-712).
- §3.2 Booking creation — insert — booking against non-OPEN amenity → ERR_INVALID_STATE 409 (app.py:901-902).
- §3.2 Check-in — insert — CHECK_IN_GRACE_MINUTES=15; out-of-window check-in → ERR_INVALID_STATE 409 (app.py:45,971-973).
- §3.3 Rent charge — insert — mismatch — endpoint responds 201 with updated resident (app.py:789).
- §3.3 Payment — insert — mismatch — endpoint responds 201 with updated resident (app.py:807).
- §3.4 Publish — insert — non-future start_at publish → ERR_INVALID_STATE 409 (app.py:1121-1122).
- §3.4 Registration/waitlist — insert — zero fee writes no EVENT_FEE ledger entry & no posture recompute (app.py:1203-1204,1266-1270).
- §3.6 Package return — insert — PACKAGE_HOLD_DAYS=7; premature return → ERR_INVALID_STATE 409 (app.py:46,1646-1647).
- §3.6 Guest pass — insert — span > guest_window_hours → ERR_VALIDATION 422 (after posture); check-in before arrival → ERR_INVALID_STATE 409; expired check-in returns 200→EXPIRED (app.py:1674-1676,1724-1729).
- §3.7 Property report — insert — active_bookings counts CONFIRMED/CHECKED_IN; avg_retention_score half-up, 0 when no residents (app.py:630-641).

Notable non-changes (PRD already uniquely pinned, verified vs impl): §2.8 validation-precedence ladder, vendor-assign error ordering (ACTIVE→trade→capacity), service-request cancel state gates, SoD-before-state on invoice approval, all fee/invoice/retention formulas, OCC-on-amenity-version.

---

## PIPELINE COMPLETE — clean pass

task_1086_multifamily_amenity_resident_experience (Expert) — **56/56 × 8 clean first-sweep** (0 iterations, 0 deletions, 0 fixes). 14 entities / 70 endpoints / 8 state machines / 9 calculations / 32 errors / 4 roles (SoD). Step 8 skipped; Step 9 = 15 edits (13 pins + 2 mismatch-revisions). 1 gen-time skip (event_amenity_wrong_property — publish-vs-create unique-derivability gap).
