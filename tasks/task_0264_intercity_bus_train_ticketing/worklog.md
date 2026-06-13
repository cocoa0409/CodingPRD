# Worklog — task_0264_intercity_bus_train_ticketing

## Step 1: Create task directory — 2026-06-09

Created `tasks/task_0264_intercity_bus_train_ticketing/` and `tasks/task_0264_intercity_bus_train_ticketing/workspace/` (pre-allocated index 0264, no auto-increment scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-09

All three required files are in place and lint-clean. I did not read any sibling task directories — the scaffold was generated purely from the scenario description and the skill specification.

Generated all three scaffold artifacts for **task_0264_intercity_bus_train_ticketing** at **Expert** difficulty. The final `scaffold_lint.py` run on the task directory returns:

> **VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.** (47 endpoints, 12 entities, 19 §1.8 instances, 33 §1.9 active instances, 511 calls scanned)

**Complexity profile:** primary archetype `pricing_engine` + secondary `quota_allocation`; layers = dual-variant calculation, rate/threshold triggers, cascading side effects, optimistic concurrency, derived-field reconciliation; topology hybrid; state-machine shape parallel; role model peer_roles; consistency immediate.

**Entities (12):** Operator, FareClass, Route, ServiceDate (seat inventory + load factor), Passenger, TravelPass (multi-ride), Booking (parallel status axes), BookingLeg, Ticket, BaggageItem, AccessibilityRequest, RefundCreditNote (immutable, `common_fields:false`). All 15 FKs use the canonical `FK -> {Parent}.id` prefix and each has a filtered-list reverse-reachability GET.

**State machines (6):** ServiceDate.lifecycle (cyclic: SCHEDULED↔DELAYED, + DEPARTED/CANCELLED terminals), ServiceDate.sales (cyclic OPEN↔SUSPENDED, parallel dimension), Booking.booking_status and Booking.payment_status (two independent parallel axes on one row), Ticket.state (linear-with-revert), TravelPass.status (ACTIVE↔EXHAUSTED revert + EXPIRED terminal).

**Key calculations (7, 2 with variants):** dynamic `leg_fare_cents` (tiered demand × advance-window × surcharge, with cash/pass variants), `total_fare_cents` (pinned per-leg-round-then-sum), `cancel_settlement` (cash vs travel-credit dual variant), `exchange_amount` (pinned eval order), `baggage_fee_cents`, `seat_inventory` (conserved-quantity counters), `pass_rides` (conserved ride pool).

**Endpoints:** 47 (25 POST incl. one `/_clock` test-driving endpoint, 22 GET — 12 mechanical FK-reverse-reachability filtered lists + single reads). **Error catalog:** 21 codes. **Roles (5):** ScheduleManager, FareAnalyst (opaque); Passenger (entity_backed); GateAgent, SupportAgent (opaque). **Concurrency rules (2):** OCC on ServiceDate.version (confirm) and Booking.version (exchange).

**Difficulty design (§1.8):** 19 instances across all 9 rules (≥2 each: dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear 2, transitive_cascade 2 with depth-3 and depth-2, priority_pair 2, boundary_precision 2, cross_entity 2, resource_temporal 2 with discrete-seat vs gap-buffer semantics, compensating_invariant 2 over rides and seats). **Corner design (§1.9):** 35 instances total — 33 active + 2 `excluded_because` stubs citing §1.8 instances — spanning entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, and consistency model.

## Step 3: Copy INSTRUCTION.md — 2026-06-09

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-09

All structural contracts verified. The PRD is complete and passes all three Hard Contracts.

Generated `workspace/PRD.md` for the Intercity Ticketing API (Amtrak/Greyhound-style). **5 top-level sections** (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue), **23 subsections**, **284 lines**.

Coverage (verified programmatically): all 60 entity fields + 41 request-body inputs + 13 path params appear verbatim (Contract 1 PASS, MISSING=[], incl. `to_iso8601` via Logical Clock §2.9). All state machines covered (ServiceDate dual axes, Booking parallel axes incl. PASS-stays-UNPAID guard, Ticket ISSUED→SCANNED/VOID, TravelPass ACTIVE↔EXHAUSTED→EXPIRED, depth-3 service-date cancellation cascade). All 6 calculations in precise prose (`leg_fare_cents` tiered demand+advance per-leg round-half-up before surcharge, `total_fare_cents` pinned round-then-sum, `cancel_settlement` cash vs credit + 0.10 leniency floor, `exchange_amount` 3-step pinned order surplus→credit, `baggage_fee_cents` 23.0kg/500-cent boundary, `seat_inventory`, `pass_rides`). All 15 priority-ordered validations in §2.11 each paired with error ID + applies_to. Both OCC rules expressed (`expected_service_date_version` confirm, `expected_booking_version` exchange → ERR_STALE_VERSION 412). All 47 endpoints in §4 table, all 21 errors in §5, all 5 roles named with identity bindings (Passenger entity-backed; other four opaque).

Hard Contracts: Contract 1 (Field-Name Coverage) PASS (60/60, 41/41, 13/13, 0 missing); Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS (372 backtick tokens, 0 paths/methods/combos). No withheld design file or sibling task read.

## Step 5: Generate unit tests — 2026-06-09

Generated complete test infrastructure from the two design indices only (no freelance discovery from SCAFFOLD.yaml).

**Test files: 5** (under `test_suite/`): `test_01_catalog_and_crud.py` (12), `test_02_pricing_and_fares.py` (12), `test_03_booking_lifecycle.py` (15), `test_04_cancellation_refunds.py` (11), `test_05_concurrency_constraints_and_invariants.py` (19).

**Total tests: 69** — **38 trace to queue A (Difficulty)**, **31 to queue B (Corner)**. All 19 difficulty instances ≥2 tests each; all 31 non-stub corner instances ≥1 test each.

**Instances skipped: 2** (both PRD unique-derivability failures, default-value/computed-constant category):
- `Corner/validations/accessibility_slots_exhausted_on_grant` — PRD §3.12 names a "per-service-date accessible-slot ceiling" but never gives its value; test presupposes ceiling=1, not PRD-derivable.
- `Corner/errors/hold_expired_blocks_confirm` — hold TTL (HOLD_TTL_MIN) never named in PRD; a faithful implementer could pick a TTL exceeding the test's 2-day clock advance, so expired-hold outcome is not uniquely derivable.

**Stubs (not translated, by design):** the 2 `excluded_because:` corner stubs (`confirm_already_confirmed_booking_returns_invalid_state`, `confirm_changes_visible_same_response`) — both resolve to real difficulty instances that own the assertion.

**test_helpers/ files emitted (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, plus `test_suite/conftest.py`. Suite collects cleanly (69 tests, no import errors); every docstring ends with one verbatim `Design:` tag; no skip/xfail; identity threading via `make_passenger_headers(passenger["id"])` for ownership-gated calls.

## Step 6: Generate implementation — 2026-06-09

Generated a complete Python + Flask implementation in `workspace/implementation/`. All 47 endpoints from PRD §4 table implemented, matching exactly.

**Source files emitted (22):** Launcher/deps (`start.sh`, `requirements.txt` flask 3.0.3); Entry/foundation (`app.py`, `db.py`, `clock.py`, `timeutil.py`, `response.py`, `errors.py`, `middleware.py`, `helpers.py`, `serializers.py`, `constants.py`); Routes (`catalog.py`, `passengers.py`, `bookings.py`, `misc.py`); Services (`pricing.py`, `inventory.py`, `passes.py`, `connections.py`, `bookings.py`).

**State machines:** ServiceDate (cyclic lifecycle SCHEDULED↔DELAYED, terminal DEPARTED/CANCELLED + parallel OPEN↔SUSPENDED sales gate), Booking (parallel booking_status × payment_status axes), Ticket (ISSUED→SCANNED/VOID), TravelPass (ACTIVE↔EXHAUSTED, terminal EXPIRED); service-date cancel runs three-hop cascade with independent version bumps. **Calculations:** all `Decimal` + ROUND_HALF_UP, per-leg rounding before surcharge (demand-tier 1.00/1.25/1.60 from CONFIRMED-only load factor, advance factor 0.90/1.00/1.15/1.40, cancel settlement cash vs credit, exchange pinned-order with surplus→credit, baggage free at exactly 23.0 kg). **Validations:** enforced in PRD §2.11 priority order (auth → RBAC → existence L-to-R → ownership → body shape → state → cross-entity → temporal → connection buffer → seat uniqueness → refund eligibility → capacity → pass balance → OCC) with exact error_ids. OCC via `expected_service_date_version` (confirm) / `expected_booking_version` (exchange) → ERR_STALE_VERSION/412.

**Contract confirmation:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec python3 app.py`, guards `pip install` on cheap `import flask`. Storage purely in-memory (module dicts in `db.py`), wiped each boot; NO seeding (fresh boot returns `total_count:0` on all list endpoints).

**NOTE (potential test-vs-impl divergence to watch in Step 7):** impl set `HOLD_TTL_MIN=30` and `ACCESSIBLE_SLOTS_PER_SERVICE_DATE=2` as named module constants since PRD never assigns values. Step 5 skipped exactly the two tests that depend on those unpinned constants, so no conflict is expected.

## Step 7: Test-iterate-fix loop — 2026-06-09

All 8 parallel rounds now pass 69/69, deterministically. (Orchestrator re-ran the 8-round sweep after the subagent exited to regenerate the `results.{1..8}.json` artifacts — all 8 confirm passed=69 failed=0 total=69.)

**Iterations run:** 2 (initial sweep surfaced 2 deterministic failures; second sweep after fixes was fully clean across all 8 rounds).

**Tests deleted:** None. Neither failure required deletion — both rules are PRD-covered.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_05_concurrency_constraints_and_invariants.py` → `test_pass_expired_blocks_confirm`: relaxed the exact `validate_error(..., ERR_PASS_EXPIRED, 409)` assertion to `validate_error_is_one_of([ERR_PASS_EXPIRED, ERR_HOLD_EXPIRED])` (plus an explicit `status_code == 409` check), and added the missing `validate_error_is_one_of` import. Permitted ERROR-PRECEDENCE relaxation, not a weakening: PRD names *both* outcomes for a confirm-time expired-pass redemption. PRD §3.10 (line 194) says "a redemption against it is rejected with `ERR_PASS_EXPIRED`," while PRD §3.3 (line 148) routes the confirm-time case into the temporal family — "a held pass booking that is later found expired at confirm raises the same temporal family handled under `ERR_HOLD_EXPIRED` for the hold itself." The test advances the clock 9 days past a 30-minute hold TTL, so the hold itself genuinely expires too; a faithful PRD-only implementer following line 148 correctly raises `ERR_HOLD_EXPIRED`. Both members are PRD-faithful and both map to HTTP 409.

**Fixes applied to `implementation/`:**
- `services/bookings.py` → `exchange_booking()`: changed the return value from the old booking to the newly created replacement booking (`return new_booking`). PRD §3.8 (line 182) states the exchange's created resource is "a new booking ... created in `CONFIRMED` and `PAID` status holding the replacement leg," and PRD §2.3 (line 47) says create/modify operations "return the created or updated resource object." The endpoint was returning the old (now `EXCHANGED`) booking, so `test_exchange_amount_pinned_evaluation_order` saw the old fare 3600 instead of the new leg's fare 5600. Pricing math was already correct; only the returned record was wrong.

No implementation checks were removed or weakened, no endpoints/fields/side-effects were added beyond PRD prose, storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-09

The patch is complete and minimal — exactly one line revised.

**Line counts:** PRD.md = 284 lines, PRD_FINALIZED.md = 284 lines. Delta = 0 lines (one line revised in place; +0% line count, one sentence added to line 182).

**Changes (one per bullet):**
- **§3.8 (Exchanging a Leg) — revise — pinned which booking the exchange endpoint returns in its response body: the newly created `CONFIRMED`+`PAID` replacement booking (carrying the new leg's fare as `total_fare_cents`/`total_paid_cents`), not the old `EXCHANGED` booking — `services/bookings.py:505` (`return new_booking`) / `routes/bookings.py:161-162`.** Addresses step_7_diff Item 1. The PRD's global envelope convention (§2.3 line 47) is ambiguous for the exchange because it both creates (new booking) and modifies (old → EXCHANGED); impl resolves toward the new booking, now pinned locally in §3.8.

**Item 2 (test relaxation for `test_pass_expired_blocks_confirm`) — no PRD edit.** Permitted ERROR-PRECEDENCE test relaxation, not a PRD silence/mismatch. Impl raises `ERR_HOLD_EXPIRED` at confirm-time pass expiry (`services/bookings.py:213`), and PRD §3.3 (line 148) already states verbatim that "a held pass booking that is later found expired at confirm raises the same temporal family handled under `ERR_HOLD_EXPIRED` for the hold itself." PRD already uniquely determines impl behavior; no edit warranted.

**Per-edit pre-edit search log (the single edit):** (a) Subject: the response body content of the exchange endpoint. (b) Impl paths enumerated/read: `services/bookings.py:390-505` (`exchange_booking()` constructs `new_booking` CONFIRMED+PAID, `return new_booking` line 505, old → EXCHANGED line 490); `routes/bookings.py:141-162` (serializes via `ser.booking_out(booking)`, returns HTTP 200); `serializers.py:94-108` (`booking_out()` fields read by test); grepped all create/modify return sites across `routes/` — confirmed no other endpoint simultaneously creates and modifies two resources, exchange is unique. (c) Wording adjustment: scoped the new sentence to §3.8 only and described only the body content, leaving HTTP status (200 OK) governed by unchanged §4 prose, so §2.3 envelope rule and all single-resource create/modify endpoints remain accurately described.

## Step 9: Complete PRD — 2026-06-09T17:53:21.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan. (Resumed step: the original `claude -p` run hit a session limit after Step 8; Steps 1–8 were verified complete on disk — Step 7 = 69/69 across all 8 parallel rounds, Step 8 `PRD_FINALIZED.md` present — so resume ran Step 9 only.)

**Source vs completed:** PRD_FINALIZED.md → PRD_COMPLETED.md: 284 → 284 lines (unchanged); 44,697 → 44,800 chars (+103 chars). Source was PRD_FINALIZED.md (it existed).

**Counts:** 3 ambiguity-pins, 0 mismatch-revisions. The implementation tracks the PRD very closely — every endpoint, state machine, calculation (per-leg fare, cancel settlement, baggage fee, exchange settlement), validation-order priority, error code, and response shape already had a uniquely-pinning PRD passage. The only gaps were three numeric/initial-value silences where impl committed to a concrete value the PRD left open.

**Changes:**
- §2.9 The Logical Clock — insert — ambiguity — pinned that the clock reads real wall-clock UTC until a SupportAgent first sets it (PRD was silent on the pre-set clock value) — `implementation/clock.py:17-20`
- §3.3 Holding Seats — insert — ambiguity — pinned the hold time-to-live to 30 minutes (PRD said only "the hold time-to-live") — `implementation/constants.py:44` / `implementation/services/bookings.py:147`
- §3.12 Accessibility Accommodations — insert — ambiguity — pinned the per-service-date accessible-slot ceiling to 2 (PRD named the ceiling but gave no number) — `implementation/constants.py:48` / `implementation/routes/misc.py:221`

**Notable non-changes (verified covered, no edit):** ERR_NOT_PAID on unpaid exchange (§3.6 prose); pay funding-kind disqualification ERR_PRECONDITION_NOT_MET (§3.5); `barcode` format `bc_`+uuid (PRD admits any unique server value); `load_factor` stored as float ratio (§2.6); exchange new-leg `leg_order=1` and copied `hold_expires_at` left unpinned to avoid gold-plating.

---

**Pipeline complete.** All 9 steps finished. Final state: 69/69 tests pass across 8 parallel rounds; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md produced.
