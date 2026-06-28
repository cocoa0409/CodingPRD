# Worklog — task_0672_parking_spot_marketplace

## Step 1: Create Task Directory — 2026-06-27T03:30:55.518Z

Directory `tasks/task_0672_parking_spot_marketplace/` was pre-assigned and already existed with `workspace/` created. No scan or index computation performed (pre-assigned to avoid ID contention). Proceeding to Step 2.

## Step 2: Generate Scaffold (Expert) — 2026-06-27T03:54:40.882Z

The `worklog.md` and `workspace/` were pre-created by the orchestrator. All three required scaffold files are correctly structured: SCAFFOLD.yaml has neither design key, and each design file has exactly its single top-level key.

The scaffold is complete and passes clean lint.

### Summary — task_0672_parking_spot_marketplace (Expert)

**Scenario:** Parking-Spot Marketplace & Monthly Rental (SpotHero/Neighbor style). Primary archetype **temporal_windowing** + secondary **pricing_engine**; topology **flat** (FK-linked peers); state-machine shape **parallel**; role model **peer_roles**; consistency **immediate**. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, scheduled/deferred actions, optimistic concurrency.

**Files written:** SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key scaffold_difficulty_design), SCAFFOLD_CORNER_DESIGN.yaml (single key scaffold_corner_design).

**Scaffold surface counts:**
- **Entities: 9** — Host, Driver, Spot, PricingEvent, Booking, AccessPass, ViolationRecord, PayoutLedgerEntry, TransferOffer.
- **State machines: 5** — Spot (cyclic LISTED↔UNLISTED), PricingEvent (linear→CANCELLED), Booking (parallel occupancy_status × settlement_status, with NO_SHOW branch), ViolationRecord (branching OPEN→{CONFIRMED,DISMISSED}), TransferOffer (branching PENDING→{ACCEPTED,DECLINED,WITHDRAWN}).
- **Concurrency rules: 2** — OCC on Spot.version (booking create) and Booking.version (transfer-offer create).
- **Calculations: 6** — booking_quote_amount (tiered, mode-a combinatorial), final_settlement_amount (threshold, overstay), host_payout_amount (per-line rounding, mode-b combinatorial), confirmed_violation_points (weighted, provisional-vs-confirmed dual variant), refund_amount (waterfall tiered), driver_standing_tier (threshold).
- **Validations: 17** (priorities 1–61, categories auth/existence/state/business_temporal/business_constraint/business_fiscal).
- **Endpoints: 42** (incl. reverse-reachability GETs, `/_clock/set_current_utc` with mandatory default `2026-04-01T00:00:00Z`, and admin `reverse-payout`).
- **Errors: 19.**
- **Roles: 4** — Anonymous (opaque), Host (entity_backed), Driver (entity_backed), PlatformAdmin (opaque).

**Difficulty design:** 9 rule_ids × 2 = **18 instances**, all 9 §0.5 rules satisfied with differentiation.
**Corner design:** **45 active instances + 2 excluded_because stubs** across all 9 taxonomy sections.
**Lint:** `scaffold_lint.py` → `VERDICT: clean lint` (42 endpoints, 9 entities, 18+45 instances, 415 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-06-27T03:54:58.416Z

Copied `./INSTRUCTION.md` → `tasks/task_0672_parking_spot_marketplace/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-27T03:59:48.952Z

**Output:** `workspace/PRD.md` (278 lines, 45707 bytes). Read SCAFFOLD.yaml only; both design YAMLs withheld.

### Section list
- **§1. Introduction** (two-sided marketplace framing, competing forces, scope)
- **§2. Global Specifications** (10 subsections): 2.1 RBAC (4 roles), 2.2 API Response Structure (FIXED verbatim), 2.3 Pagination, 2.4 Common Resource Properties & Versioning (AccessPass + PayoutLedgerEntry `common_fields: false`), 2.5 Cascading State Changes, 2.6 Monetary/Points/Precision (cents, round-half-up, bps), 2.7 OCC (both rules + reverse-payout version guard), 2.8 Nested Retrieval (left-to-right), 2.9 Logical Clock (default `2026-04-01T00:00:00Z`), 2.10 Validation Ordering (priority chain 1→61)
- **§3. Business Logic & Workflows** (9 subsections): onboarding/wallet, spot listing cycle, pricing events & booking quote, occupancy/access-pass/gate, confirmation+checkout+overstay, cancellation/refund/payout-reversal, host payouts & ledger, violations/scoring/standing, reservation transfer
- **§4. Endpoint Definitions** (42-row table)
- **§5. Error Code Catalogue** (19-row table)

### Hard Contract reports: Contract 1 (Field-Name Coverage) PASS; Contract 2 (Rule Coverage — 18 priorities, 2 OCC + reverse-payout guard, 14 transitions/5 machines, 6 calculations, 19 errors, sibling-branch symmetry) PASS; Contract 3 (§3 Path Purity — 391 backtick tokens, 0 paths/methods) PASS.

### Coverage notes
- Constants embedded with unit conversion (refund tiers 604800s=7d / 86400s=1d; escalation cap 17500 bps; overstay 15000 bps = 1.5x base hourly; platform_fee_bps=1500, overstay_grace_minutes=15, gate_opens_remaining=2).
- Booking-create params scattered: core in §3.3, `expected_spot_version` cross-referenced from §2.7.
- Scaffold quirk reflected: reverse-payout carries `expected_booking_version` with stale-parent semantics.
- No design YAMLs and no sibling task dirs read.

## Step 5: Generate Unit Tests — 2026-06-27T15:08:00.000Z

Generated complete test infrastructure for **task_0672_parking_spot_marketplace** per the design-index-only contract in the unit-test-generator skill.

### Stage 1 — `test_helpers/` (8 modules + barrel)
- **`types.py`** — 9 status enums, UserRole, and TypedDicts for all 9 entities. AccessPass and PayoutLedgerEntry correctly carry only `id`+`created_at` (PRD §2.4 append-only); the 7 versioned entities carry `updated_at`+`version`.
- **`api_client.py`** — `ApiClient(GenericApiClient)`, one method per endpoint (all 40 routes in PRD §4).
- **`api_errors.py`** — all 18 error IDs + HTTP-status map, registered with the framework.
- **`constants.py`** — bps conventions, refund tiers, kind weights, escalation/standing thresholds, gate-open count, clock default.
- **`factories.py`** — per-entity payload builders; optional fields (`platform_fee_bps`, `overstay_grace_minutes`) omittable, all other inputs required.
- **`assertions.py`** — per-entity shape checkers with append-only branching.
- **`test_users.py`** — opaque shared headers for Admin/Anonymous + per-instance `make_host_headers`/`make_driver_headers` for the two `entity_backed` roles (identity threading).
- **`fixtures.py`** — composite setup chains (reserved/checked-in bookings, suspended driver, pending transfer offer, no-show+earning) used across the suite.

### Stage 2 — `test_suite/` (conftest + 6 files, 81 tests)
- `test_01_pricing_and_settlement.py`, `test_02_violation_scoring.py`, `test_03_state_machines_and_cascades.py`, `test_04_validations_and_boundaries.py`, `test_05_invariants_and_concurrency.py`, `test_06_crud_gate_and_rbac.py`.

### Coverage (verified by script)
- **Queue A (Difficulty):** all 18 instances across 9 rules, each with **≥2 tests** tagged `Design: Difficulty/<rule_id>/<name>`.
- **Queue B (Corner):** all **non-stub** instances covered with **≥1 test** tagged `Design: Corner/<section>/<name>`; the 2 `excluded_because` stubs were not translated and their `difficulty_instance` cross-references both resolve to real difficulty instances.
- Every test docstring carries a verbatim PRD citation (110 quoted passages spot-checked against PRD.md, all grounded — the 2 flagged were `...`-elided two-fragment quotes whose halves are each verbatim). No untagged/dual-tagged tests, no `skip`/`skipif`/`xfail`.

### Adjudication notes
- Priority-pair conflict tests pass the Core rule because PRD §2.10 states the full validation order verbatim (P40<P50, P20<P30, P3<P11), so the asserted winner is uniquely derivable.
- All files compile, import cleanly against the installed `prd_bench_local_runner.testing` framework, and `pytest --collect-only` reports 81 tests with no errors.

## Step 6: Generate Implementation — 2026-06-27T15:08:00.000Z

Generated a complete Python + Flask implementation for the parking-spot marketplace API at `workspace/implementation/`.

### Structure
- `start.sh` — foreground launcher with guarded `pip install` (only installs when Flask is missing) and `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — app factory, blueprint registration, error handlers (ApiError → standard error envelope; 404/405/500 also enveloped)
- `db.py` — in-memory store (starts empty, no seeding), system-field helpers (`make_versioned`/`make_lightweight`/`touch`)
- `clock.py` — logical clock defaulting to `2026-04-01T00:00:00Z`
- `errors.py`, `response.py`, `middleware.py`, `serialize.py`, `util.py` — foundation
- `services/calculations.py` — all 6 calculation rules using `Decimal`/`ROUND_HALF_UP`
- `services/domain.py` — cross-entity cascades (violation creation, ledger posting, refund, suspension auto-cancel)
- `routes/` — one module per resource group (hosts, drivers, spots, pricing_events, bookings, access_passes, transfer_offers, violations, clock)

### Verification (all passing via live HTTP smoke tests)
- Response envelope, pagination, auth/RBAC/ownership, full validation-priority ordering
- Quote engine (HOURLY/DAILY ceil, MONTHLY flat-30-day, surge, weekend uplift, multiply-then-round, base-hourly floor)
- Overstay settlement, wallet top-up floor, host payout per-line fee rounding, EARNING/REVERSAL, lifetime_payout conservation
- Violation escalation (+25%/prior, cap +75%), provisional-vs-confirmed dual variant, standing tiers, suspension cascade auto-cancelling RESERVED bookings with tiered refunds
- Transfer offers (make-whole wallet conservation, self-transfer + stale-version guards), refund tiers, no-show flow, access-pass redemption, OCC, spot listing cycle, half-open interval conflict

### Notable design decision
PRD §2.9 says advancing the clock makes RESERVED bookings *eligible* to be marked no-show, with a dedicated `mark-no-show` endpoint. Implemented `/_clock/set_current_utc` to only advance time (not auto-mark), following the PRD prose literally. Store is empty on fresh boot — correct for `--isolation per-test-server`.

## Step 7: Run Tests and Iterate — 2026-06-27T15:25:00.000Z

All 8 parallel rounds pass with 81/81 tests green, zero failures and zero errors. The clean sweep confirms the fixes hold and the earlier "could not be restarted" setup errors (host-saturation artifacts) did not recur.

## Summary

**Iterations run:** 3 sweeps total — initial diagnostic sweep (8 failing across the union: 4 real, 4 host-saturation restart errors), one after the first batch of fixes (1 remaining), one final clean sweep (81/81 × 8 rounds).

**Tests deleted:** None. Every failure traced either to a real implementation bug or to a test artifact that was inconsistent with PRD prose (fixable, not PRD-silent).

**Fixes applied to `test_suite/`:**
- `test_05_invariants_and_concurrency.py` :: `test_stale_booking_version_on_reverse_payout` — assertion changed from `ERR_STALE_BOOKING_VERSION` to `ERR_STALE_SPOT_VERSION`. PRD §2.7 verbatim pins the reverse-payout version-mismatch error to "`ERR_STALE_SPOT_VERSION` semantics for stale parents"; the old assertion directly contradicted the PRD sentence (a TEST-vs-PRD consistency bug at the assertion layer). Docstring updated to quote the full PRD sentence including the pinned error_id.
- `test_03_state_machines_and_cascades.py` :: `test_confirm_suspension_autocancels_reserved_and_refunds` — booking window widened from `[10:00,11:00)` (1h) to `[10:00,12:00)` (2h). The test's own narrative and downstream assertions require `quoted_amount_cents == 800` and `wallet_balance_cents` restored to 5000, but the 1-hour window at the fixture's default `base_hourly_cents=400` (Monday, no surge/weekend per PRD §3.3) produces a quote of 400. The fixture constructed a precondition inconsistent with the pinned quote; widening to 2h makes the setup faithful (2 × 400 = 800).

**Fixes applied to `implementation/`:**
- `routes/spots.py` :: `create_spot` — reordered the referenced-`host_id` existence check (`ERR_NOT_FOUND`) to run before the ownership check (`ERR_NOT_RESOURCE_OWNER`), per PRD §2.10 validation ordering (existence precedes ownership) and §2.8 (body-referenced resources resolved with `ERR_NOT_FOUND`).
- `routes/bookings.py` :: `reverse_payout` — removed the premature `ERR_INVALID_STATE` "not finalized" gate. PRD §3.6 describes reverse-payout solely as a ledger eligibility check: "a reversal attempted on a booking with no posted earning ... is rejected with `ERR_NO_REVERSIBLE_PAYOUT`." Reverse-payout is not a state-machine transition, so a still-RESERVED booking (no posted earning) now correctly surfaces `ERR_NO_REVERSIBLE_PAYOUT` after the OCC version check, matching the §2.10 ordering (version-match before reverse-payout eligibility).

**Note on flaky setup errors:** The initial sweep also showed 4 "API server ... could not be restarted" setup errors scattered across different rounds/tests. These are host-saturation artifacts of the 8×-concurrent per-test-server isolation (peak ~8× boot load), not code defects — `start.sh` already uses a conditional pip install and `app.py` boots a stateless in-memory Flask app. They did not recur in either subsequent sweep.

## Step 8: Finalize PRD — 2026-06-27T15:32:00.000Z

**Line counts:** PRD.md = 278 lines, PRD_FINALIZED.md = 278 lines. Delta: 1 line revised (in place, no line added/removed), 0% line-count delta. Net change is one rewritten sentence in §3.6.

### Changes (one bullet per change)
- **§3.6 (Cancellation, Refunds, and Payout Reversal) — revise — pinned that reverse-payout is not a state-machine transition: it has no `occupancy_status` state check (no `ERR_INVALID_STATE` gate), eligibility is determined solely from the ledger, and a booking with no posted earning — including a non-finalized one still in `RESERVED` — is rejected with `ERR_NO_REVERSIBLE_PAYOUT` after the §2.7 version check — `routes/bookings.py:377-404`** (esp. lines 393-400, no occupancy check; OCC at 390-391 precedes eligibility at 398-400).

### step_7_diff items that needed NO PRD edit (and why)
- **Tests deleted: None** — nothing to align.
- **test_05 `ERR_STALE_SPOT_VERSION` assertion** — PRD §2.7 (line 113) already verbatim pins reverse-payout version mismatch to "`ERR_STALE_SPOT_VERSION` semantics for stale parents". Already determined; kept verbatim.
- **test_03 booking-window widening** — pure fixture arithmetic bug; PRD §3.3 already pins the quote calculation. No silence.
- **spots.py create_spot existence-before-ownership reorder** — PRD §2.10 already pins existence (`ERR_NOT_FOUND`) before ownership (`ERR_NOT_RESOURCE_OWNER`); §2.8 pins body-referenced resources to `ERR_NOT_FOUND`. Already uniquely determined; kept verbatim.

## Step 9: Complete PRD — 2026-06-27T15:38:00.000Z

**Source vs. completed:** PRD_FINALIZED.md = 278 lines / 46,288 chars; PRD_COMPLETED.md = 278 lines / 47,190 chars. Char delta: +902 bytes; line count unchanged (all edits in-paragraph).

**Counts:** 4 changes total — 3 ambiguity-pins, 1 mismatch-revision.

**Per-change list:**
- **§3.1 — insert — ambiguity** — pinned that wallet-topup `amount_cents` must be a positive integer; zero/negative rejected with `ERR_INVALID_REQUEST` — `routes/drivers.py:57-58`
- **§3.4 (AccessPass paragraph) — insert — ambiguity** — pinned that gate redemption looks the pass up by `qr_token` alone, requires the `booking_id` to still resolve, and returns the updated `AccessPass` as a single object; and that `GET /bookings/{id}/access-pass` returns an array (0 or 1) rather than a single object — `routes/access_passes.py:14-33`, `routes/bookings.py:217-226`
- **§3.4 (no-show paragraph) — revise — mismatch** — removed "or by the server during a clock advance"; pinned no-show is marked solely via the explicit admin mark-no-show endpoint (clock advance only makes a booking *eligible*, never auto-marks), and a premature/wrong-state attempt yields `ERR_INVALID_STATE` — `routes/bookings.py:351-374`, `routes/clock_route.py`
- **§3.6 — insert — ambiguity** — pinned that the reverse-payout response returns the newly posted `REVERSAL` ledger entry object (not the booking), as a single object with `response_type` `object` — `routes/bookings.py:402-404`

**Behaviors checked and confirmed already-pinned (no change):** auth/role/ownership and validation order (§2.1/§2.10), envelope and pagination (§2.2/§2.3), versioning/cascade (§2.4/§2.5), reverse-payout `ERR_STALE_SPOT_VERSION` semantics (§2.7), quote/surge/weekend/overstay/refund/fee/escalation formulas and rounding (§3.3/§3.5/§3.6/§3.7/§3.8), surge tie-break, prior-confirmed ordering, check-in window bounds, transfer make-whole conservation, all state-machine transitions.
