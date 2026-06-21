# Worklog — task_0274_season_ticket_holder

Scenario: 274. Season Ticket Holder Management: seat/section inventory, full/partial-season plans, renewal & price changes, seat relocation/upgrade, payment plan, ticket forwarding/resale, playoff/priority points, parking add-on

## Step 1: Create task directory — 2026-06-10

Created `./tasks/task_0274_season_ticket_holder/workspace`. Next index resolved to 0274 (prior max 0273).

## Step 2: Generate scaffold — 2026-06-10

Generated all three scaffold artifacts for **task_0274_season_ticket_holder** and verified them against the skill's own spec. `scaffold_lint.py` returns **VERDICT: clean lint**, all three files parse, all `grounds` references resolve, and the file-key split is honored (neither design key leaks into SCAFFOLD.yaml).

**Files written**:
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency_rules) — 1466 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) — 1137 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) — 1136 lines

**Complexity profile**: Quota/allocation primary + Pricing-engine secondary; flat topology; cyclic state-machine shape; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. (Expert band.)

**Counts**:
- **Entities**: 11 — Section, Seat, Account, SeasonPlan, Subscription, SeatAssignment, PaymentPlan, Installment, TicketTransfer, ParkingZone, ParkingAddOn
- **State machines**: 3 — Subscription (cyclic: ACTIVE↔RELOCATING, ACTIVE↔RENEWAL_OFFERED, +SUSPENDED/CANCELLED), TicketTransfer (branching fork: PENDING→{FORWARDED, LISTED}→SOLD with divergent side-effects), PaymentPlan (self-loop pay + DEFAULTED/CANCELLED). Plus 2 OCC concurrency_rules (relocate-begin, renewal-accept) on Subscription.version.
- **Calculations**: 5 — renewal_price (tiered + multiplier + loyalty + max floor; full/partial variants), priority_points_accrual (standard/playoff variants), resale_payout (round-each-fee-then-sum, pinned), payment_plan_installments (waterfall + remainder-to-last), cancellation_refund.
- **Validations**: 13 ordered rows across auth/existence/state/business_* categories.
- **Endpoints**: 51 (includes per-entity single+list GETs and FK reverse-lookup GETs; one `/_accounts/{id}/grant-points` test-driving endpoint).
- **Error catalog**: 14 codes.
- **Roles**: 3 — BoxOfficeAgent (opaque), AccountHolder (entity_backed:Account), FinanceClerk (opaque).

**Difficulty/corner instance counts**:
- §1.8: **18 instances** — all 9 Difficulty Rules × exactly 2 instances each.
- §1.9: **34 instances** — 30 active corner tests + 4 `excluded_because` stubs.

All formula-derived asserts pinned as literals (renewal full=200000 vs partial=110000, floor-bind=100000, points 100 vs 300, resale payout 8965, waterfall [50000,75000,75000], refund 30000).

## Step 3: Copy INSTRUCTION.md — 2026-06-10

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10

Generated `workspace/PRD.md` (257 lines) from the scaffold. Sections: §1 Introduction; §2 Global Specifications (RBAC, response envelope, pagination, common resource properties, inventory counters/derived-field reconciliation, OCC on Subscriptions, monetary/points precision, path resolution + validation priority order, terminal states); §3 Business Logic (12 scattered subsections); §4 endpoint table (53 endpoints incl. `/_accounts/{id}/grant-points`); §5 error catalogue (14 errors).

Hard Contract reports: Field coverage PASS (52/52), Rule coverage PASS (validations, 2 OCC rules, 3 state machines, 5 calculations, 14 error IDs, cascades, sibling-branch symmetry all expressed), Path purity PASS (0 path/method tokens in §3). Confirmed: neither design YAML was read.

## Step 5: Generate unit tests — 2026-06-10

**Test files:** 6 test files (+ `conftest.py`) in `test_suite/`, **64 test functions**.
- test_01_pricing_and_points.py — 12; test_02_lifecycles_and_cascades.py — 14; test_03_constraints_and_conflicts.py — 17; test_04_conservation_invariants.py — 5; test_05_entities_crud.py — 8; test_06_access_reads_and_concurrency.py — 8.

**test_helpers/ (9):** __init__.py, types.py, api_client.py (51 endpoint methods), api_errors.py (14 error IDs), assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

**Queue A — Difficulty (18 instances):** 17 translated (≥2 tests each), 1 skipped:
- `cross_entity_state_dependency/parking_addon_requires_subscription_active` — PRD §3.12 never states ParkingAddOn creation requires ACTIVE subscription; asserted ERR_INVALID_STATE has no PRD coverage → skipped.

**Queue B — Corner (34 = 30 non-stub + 4 stubs):** 29 translated (≥1 test each), 1 skipped:
- `rbac/holder_cannot_forward_other_holders_assignment_not_owner` — instance asserts ERR_NOT_RESOURCE_OWNER but PRD §3.9 states transfer creation on a non-owned assignment is rejected with ERR_SECTION_MISMATCH; fails unique-derivability → skipped.

All 64 tests carry exactly one `Design:` tag; 95 PRD citation segments confirmed verbatim; 14 computed literals re-derived; no skip/xfail; pytest collects 64 cleanly.

## Step 6: Generate implementation — 2026-06-10

Generated Python + Flask implementation at `workspace/implementation/` (18 files): start.sh (foreground, reads $PORT, binds 0.0.0.0, `exec python3 app.py`), requirements.txt (Flask 3.0.3), app.py, db.py (in-memory dicts + RLock, no seeding), errors.py (14 codes), response.py (PRD envelope), middleware.py (X-User-ID/Role auth + RBAC), helpers.py, calculations.py (5 calc rules, Decimal ROUND_HALF_UP), services.py, routes/ (7 modules).

**Endpoints:** 51 — exact 1:1 with PRD table. **Storage:** in-memory dicts keyed by UUID, no persistence, no seeding (fresh GET /sections → []).

Key behaviors verified: full/partial activation pricing w/ 100000-floor, points accrual incl. playoff, relocation begin/confirm/abort w/ OCC (412) + section/window-mismatch (422), resale round-each-then-sum, installment waterfall remainder-to-last, cancel cascade (seat release, points clawback, plan cancel + installment void, parking release, refund), default→suspend cascade, renewal accept reprice, closed-interval seat conflict, parking capacity, terminal-state guards, email uniqueness, validation precedence chain (state before ownership per §2.8). start.sh HTTP-ready <1s on test port.

## Step 7: Run tests and iterate — 2026-06-10

**Iterations run:** 2 (baseline sweep → 1 fix → confirming sweep).

**Initial state:** 2 stable failures across all 8 rounds (no flakiness): `test_seat_window_adjacency_is_a_conflict` and `test_seat_window_overlap_same_window_conflict` (test_03_constraints_and_conflicts.py). Both: "Expected response_type 'error', got 'object'" — a seat assignment that should be rejected with `ERR_SEAT_WINDOW_CONFLICT` was succeeding.

**Diagnosis:**
- STEP 1a COVERAGE — PASS. Both cite PRD §3.4 verbatim (closed-interval window overlap, shared-endpoint = collision).
- STEP 1b UNIQUE DERIVABILITY — PASS. §3.4 + §3.1 establish the same physical seat is modeled as multiple `Seat` rows (one per window) sharing physical location (section + row_label + seat_number); the window guard keys on physical location, not Seat row id (under a row-id reading the guard would be dead code at initial assignment → confirms physical-location is the unique faithful reading).
- STEP 2 CONSISTENCY — both fixtures build two distinct Seat rows sharing the same physical location with overlapping/adjacent windows; PRD-faithful.
- STEP 3 — implementation was the bug.

**Fix applied to implementation:**
- `workspace/implementation/routes/subscriptions.py`, `_check_seat_window_conflict` — conflict scan keyed on `sa["seat_id"] == seat["id"]` (same Seat row), which never fires for two distinct rows. Changed to key on physical location (section_id + row_label + seat_number) so the same physical seat resold as distinct rows into overlapping windows is rejected with `ERR_SEAT_WINDOW_CONFLICT`. Verified no regression to relocation-confirm call site or section-mismatch precedence test.

**Tests deleted:** none. **Fixes to test_helpers/:** none. **Fixes to test_suite/:** none.

**Final sweep:** all 8 parallel rounds clean — 64/64 passed, 0 failed/errors/skipped in every round.

## Step 8: Finalize PRD — 2026-06-10

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 257; PRD_FINALIZED.md = 257 (+0.0%; one §3.4 sentence revised in place).

**Change (1):**
- §3.4 — revise — Pinned the seat-window-conflict guard's notion of "the same physical seat" to mean any `Seat` row sharing the same `section_id`, `row_label`, and `seat_number` (physical location), not the same `Seat` row `id`. One physical seat is modeled as multiple `Seat` rows (one per season window). — `routes/subscriptions.py:394-399` (`_check_seat_window_conflict`).

**Pre-edit search log:** enumerated `_check_seat_window_conflict`, both callsites (initial-assignment no-exclude, relocation-confirm with exclude_subscription_id), the separate `ERR_SECTION_MISMATCH` path (left untouched), `windows_overlap` (closed-interval, kept verbatim), seat creation (no physical-location uniqueness constraint). Wording adjustment: "some other ASSIGNED SeatAssignment" to stay true at both callsites; avoided implying any seat-creation uniqueness constraint.

## Step 9: Complete PRD — 2026-06-10

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` (existed → copied). Line counts: 257 → 257 (all edits in-paragraph; char delta +3,018). Counts: **16 ambiguity-pins, 0 mismatch-revisions** (every gap was PRD silence over an impl-chosen detail; no place described different behavior than impl).

Changes (all in-paragraph inserts):
- §2.3 — list sort breaks created_at ties by id ascending (helpers.py:64)
- §3.1 — section list filterable by tier (inventory.py:58); section-seats reverse lookup accepts status filter (inventory.py:69)
- §3.2 — duplicate email → ERR_INVALID_REQUEST 422 (accounts.py:36); account-subscriptions reverse lookup accepts status filter (accounts.py:85)
- §3.3 — season-plan list filterable by plan_type (inventory.py:184); activation non-PENDING/non-ACTIVE/no-ASSIGNED → ERR_INVALID_STATE 409 (subscriptions.py:110); renewal accept check order pinned (subscriptions.py:263)
- §3.4 — assign against non-PENDING → ERR_INVALID_STATE, CANCELLED → ERR_VALIDATION_FROM_TERMINAL (seat_assignments.py:39); subscription reverse lookup status filter (subscriptions.py:344)
- §3.5 — relocate confirm order (mismatch → AVAILABLE → window-overlap) pinned (subscriptions.py:174)
- §3.7 — pricing runs before accrual at activation/renewal (subscriptions.py:117,271)
- §3.9 — forward eligibility error order + conditional reassignment no-op (transfers.py:149); non-ACTIVE buyer → ERR_TRANSFER_NOT_ELIGIBLE 409 (transfers.py:223)
- §3.10 — plan-installments reverse lookup status filter (payments.py:98); bad/missing seq → ERR_NOT_FOUND 404, default w/ no SCHEDULED → ERR_INVALID_STATE 409 (payments.py:127,177)
- §3.11 — refund recorded in refund_cents, surfaced on plan only after cancellation, absent when no plan (helpers.py:265, subscriptions.py:329)
- §3.12 — parking against non-owned subscription → ERR_NOT_RESOURCE_OWNER 403 before capacity guard (parking.py:37); subscription parking reverse lookup status filter (subscriptions.py:367)

## Pipeline complete — 2026-06-10

All 9 steps done. Final state: 64/64 tests pass across 8 parallel rounds. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9), test_suite/ (6 files, 64 tests), implementation/ (18 files, 51 endpoints).
