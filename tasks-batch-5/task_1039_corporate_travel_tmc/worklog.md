# Worklog — task_1039_corporate_travel_tmc

## Step 1: Create task directory — 2026-07-16T11:23:00.000Z

Created `./tasks/task_1039_corporate_travel_tmc/` and `workspace/` subdirectory. Folder pre-assigned (ID scan skipped). Difficulty: Expert (passed only to Step 2 scaffold-generator).

## Step 2: Generate scaffold (Expert) — 2026-07-16T11:47:00.000Z

Three artifacts written; all parse under yaml.safe_load. Lint verdict: clean — 45 endpoints, 10 entities, 18 §1.8 instances, 17 active §1.9 instances, 246 calls scanned.

- Archetype: ledger_reconciliation + quota_allocation; topology flat (peer entities under /tmc, FK-linked, Booking↔UnusedTicketCredit cyclic reference); role model segregation_of_duties.
- Entities (10): TravelPolicy, Traveler, Vendor, NegotiatedRate, TripRequest, Booking, GroupBooking, UnusedTicketCredit, Invoice, InvoiceLine.
- Endpoints (45): incl. 2 ops endpoints (POST /_clock/set_current_utc default 2026-07-01T00:00:00Z, POST /tmc/maintenance/run-sweep); every FK has filtered-list reverse GET.
- State machines (7): TripRequest (cyclic revision loop + branching approval routing), NegotiatedRate (ACTIVE↔EXHAUSTED → EXPIRED), Booking (branching cancel/exchange/refund), GroupBooking, UnusedTicketCredit, Invoice (DISPUTED→RECONCILED loop), Traveler.
- Calculations (9): dual-variant trip estimate vs actual; realized vs potential savings; exchange settlement (nested max/conditional); invoice reconciliation (pinned per-line round-then-sum, 0.035 fee); rate-usage consumption; credit residual conservation; group aggregate-capacity; traveler half-open overlap.
- Validations: 16 priority-ordered rows. Error catalog: 16 codes. RBAC roles (5): TravelManager (opaque), Traveler (entity_backed), Approver (entity_backed, cannot self-approve), FinanceOfficer (opaque), System (opaque). Concurrency: 1 OCC rule (booking-create-stale-trip, 412 on stale expected_trip_request_version).
- §1.8: 9 rules × 2 = 18 instances. §1.9: 17 real corner instances across 8 sections + 7 excluded_because stubs.

## Step 3: Copy INSTRUCTION.md — 2026-07-16T11:47:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-16T11:53:00.000Z

Generated workspace/PRD.md, 270 lines. Sections: §1 Intro, §2 Global Specs (RBAC 5 roles, response envelope, pagination, common props, monetary/rounding MGMT_FEE_RATE 0.035 round-half-up per-line-before-sum, logical clock default 2026-07-01T00:00:00Z + sweeps, referential integrity + 16-step validation priority order, OCC on booking creation, cascading consistency), §3 Business Logic (8 subsections), §4 endpoint table (45), §5 error table (16). Hard contracts: field coverage 0 missing across 79 required names; §3 path purity 0 violations; all 9 calculations rendered in prose. Undeclared scaffold constants: NONE (all thresholds are entity input fields; MGMT_FEE_RATE declared 0.035). No downstream constant-patching required.

## Step 5: Generate unit tests — 2026-07-16T12:09:00.000Z

test_helpers/ (9 files) + test_suite/ (6 files + conftest), 53 tests. Queue A (§1.8): all 18 instances × 2 tests each = 36. Queue B (§1.9): all 17 non-stub instances × 1 test = 17. 7 excluded_because stubs correctly not translated. Instances SKIPPED by PRD-first filter: NONE (clean design — every non-stub had verbatim PRD coverage + uniquely-derivable outcome). Adjudication notes: two priority-pair precedence instances legit (PRD §2.7 fixed priority order); exchange residual-credit test asserts credit by traveler+value (PRD §3.4) not origin_booking_id (PRD-unpinned). All 53 collect; every docstring ends with one resolving Design: tag; no skip/xfail.

## Step 6: Generate implementation — 2026-07-16T12:09:00.000Z

workspace/implementation/: 19 .py + start.sh + requirements.txt. Core: app.py, store.py (in-memory + logical clock), errors.py, envelope.py, auth.py, validate.py, common.py, logic.py. 10 route modules (Blueprints): clock, policies, travelers, vendors, rates, trips, bookings, groups, credits, invoices. Endpoints wired: 45 (== scaffold; verified route-count 45). ast.parse passes on every .py; start.sh boots on $PORT/0.0.0.0 foreground, create POST → 201. In-memory only, no seeding. Key decisions: booking-create validation follows global priority order literally (ERR_STALE_VERSION precedes ERR_APPROVAL_REQUIRED); consumed_count/actual_cost count {TICKETED, EXCHANGED}; version starts 1, +1 per mutation incl cascades; email uniqueness among ACTIVE → ERR_INVALID_REQUEST; approver grade too low → ERR_APPROVAL_RANK_TOO_LOW.

## Step 7: Test-and-fix loop — 2026-07-16T12:15:00.000Z

All 8 rounds pass 53/53 (2 waves of 4 via sweep.sh). Clean sweep.

**Iterations run:** 2 (baseline sweep + 1 fix sweep).

**Tests deleted:** None. No PRD-silence or non-unique-derivability issues found.

**Fixes applied to test_helpers/:**
- test_helpers/fixtures.py — added module-level get_credit(credit_id) helper (GETs a credit by id via the shared api_client singleton, auto-exported through `from .fixtures import *`). Needed because the module-level scenario helper _partial_redemption had no way to fetch a credit without the pytest `api` fixture, which is not in scope outside test functions.

**Fixes applied to test_suite/:**
- test_suite/test_04_cascades.py — the module-level helper _partial_redemption() (used by test_partial_redemption_applies_min_and_leaves_residual and test_credit_value_conserved_across_partial_redemption) referenced the pytest fixture `api`, which only exists inside test-function bodies, so both tests died with `NameError: name 'api' is not defined` in all 8 rounds. Replaced api.get_unused_ticket_credit(credit["id"], MGR) with the new get_credit(credit["id"]) module-level helper and imported it. This is a test-layer bug fix (STEP 2); the assertions (credit_applied_cents = min, residual, PARTIALLY_USED, value conservation) trace verbatim to PRD §3.3/§3.5 and were left unchanged.

**Fixes applied to implementation/:** None. The implementation already correctly supported partial redemption (credit_applied_cents, residual_value_cents, PARTIALLY_USED, face_value_cents, redeem_credit_id) and passed once the test helper was corrected.

Final state: 53/53 passing across all 8 rounds, 0 failures, 0 errors, 0 flakiness.

## Step 8: Finalize PRD — 2026-07-16T12:16:00.000Z

PRD_FINALIZED.md is a verbatim copy of PRD.md — ZERO edits (270 lines, byte-identical via diff). The entire step_7_diff was a pure test-layer scoping bug fix (module-level helper referencing pytest `api` fixture out of scope) with zero implementation/ fixes and zero deletions. Traced partial-redemption behavior (logic.py apply_credit: applied=min(residual, fare); REDEEMED+redeemed_by_booking_id when residual→0 else PARTIALLY_USED) to PRD §3.3/§3.5 — all fields (credit_applied_cents, residual_value_cents, face_value_cents, redeem_credit_id) and the conservation invariant already uniquely pinned. No PRD silence/mismatch → no patch warranted.

## Step 9: Complete PRD — 2026-07-16T12:22:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md. 270 lines, +1,216 chars, 7 in-paragraph edits (no new sections). 7 ambiguity-pins, 0 mismatch-revisions.

- §2.3 Pagination — insert — limit clamped to [1,100]; non-integer limit/offset → defaults; negative offset → 0 (envelope.py:47-66).
- §2.3 Pagination — insert — created_at ties broken by ascending creation order (common.py:31, logic.py:234).
- §2.4 Common Resource Properties — revise — version starts at 1 (store.py:86).
- §3.1 Program Config — insert — duplicate email among ACTIVE travelers → ERR_INVALID_REQUEST (travelers.py:38-40).
- §3.2 Trip Approval — insert — sub-grade approver (or X-User-ID matching no traveler) at PENDING_MANAGER → ERR_APPROVAL_RANK_TOO_LOW (trips.py:91-92).
- §3.4 Exchanges — insert — new booking inherits segment_type/fare_basis/old vendor/rate/datetimes for non-overridden options, credit_applied_cents=0; residual credit's origin_booking_id/vendor_id from old booking (bookings.py:187-207).
- §3.7 Savings Reporting — insert — booked_count = count of TICKETED/EXCHANGED bookings whose vendor_id is this vendor; report body carries no common server-managed fields (logic.py:157-180, vendors.py:61-65).

Notable non-change: did NOT add ownership enforcement to §2.1 — impl performs no positive owner-vs-X-User-ID check on Traveler ops (only self-approval SoD comparison); §2.1's ownership sentence is a conditional that never fires.

## Pipeline complete — 2026-07-16T12:22:30.000Z

All 9 steps done. Final: 53/53 tests pass across all 8 stability-sweep rounds. Deliverables: SCAFFOLD.yaml (+ 2 design files), workspace/PRD.md, PRD_FINALIZED.md (verbatim copy), PRD_COMPLETED.md (7 ambiguity-pins), test_helpers/, test_suite/ (53 tests), workspace/implementation/ (45 endpoints, in-memory Flask).
