# Worklog — task_1372_commercial_truck_dealership_service

## Step 1: Create Task Directory — 2026-08-13T01:40:00.000Z

Task directory `tasks/task_1372_commercial_truck_dealership_service/` and `workspace/` pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per command args).

## Step 2: Generate Scaffold — 2026-08-13T02:33:00.000Z

All three scaffold artifacts are written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts
- **Entities: 15** (CustomerAccount, FactoryBuildSlot, FactoryOrder, Unit, FloorPlanEntry, TradeAppraisal, ServiceBay, MobileServiceUnit, RepairOrder, RepairOrderLine, ServiceBooking, WarrantyClaim, Part, PartsSale, PartsSaleLine)
- **State machines: 8**, five of them non-linear (FactoryOrder hold-expire/re-hold cycle, TradeAppraisal offer/counter loop, WarrantyClaim deny/appeal/re-adjudicate loop, Unit reconditioning loop, RepairOrder with two independent state dimensions)
- **Endpoints: 80** (flat topology under `/dealership`, incl. logical clock with pinned default `2026-08-01T00:00:00Z` and a daily ops sweep checkpoint)
- **Error catalog: 53**
- **Difficulty instances (§1.8): 22** across all nine rules — dual-variant calcs on two domains (floor-plan actual-vs-projected payoff; appraisal book-vs-market ACV), combinatorial formulas in all three modes (tiered/multiplier order pricing; per-line-then-sum parts rounding; pinned evaluation-order RO totals), two depth-3+ transitive cascades (adjudication → RO → AR → credit posture; committed-cancel → slot counters → pool posture), two priority-conflict pairs on different category pairs (state/fiscal, constraint/temporal), boundary checks on three metrics (aging day 90/91, slot availability zero, 120-minute downtime grace), three cross-entity state gates on distinct pairs, two overlap semantics (bay half-open vs mobile closed-with-travel-buffer), and two compensating invariants (slot availability count; floor-plan ledger cents via OCC-guarded adjustment pairs)
- **Corner instances (§1.9): 64** (55 active + 9 `excluded_because` stubs), spanning all nine claim-guide sections: envelope/pagination/clock, entity creation-defaults-computed-immutability-404-FK-reachability, state-machine invalid-from/terminal-lockdown/idempotency/auto-transitions/cascades, calculation correctness at pinned literals, 14 validation violation probes, RBAC role-denial/ownership/segregation-of-duties, OCC stale-version on both concurrency rules, derived-field reconciliation, and immediate consistency

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(670 calls scanned, 0 violations; first clean run achieved after one YAML-quoting fix, plus two post-lint replay corrections: four appraisal offers that exceeded their own MARKET ACV cap were lowered into range, and three arithmetic literals — commit total 14635000, 5-day accrual 9665, 181-day accrual 349865 — were recomputed and pinned. All formula-derived asserts were verified by executing the declared formulas in Python.)

## Step 3: Copy Shared Files — 2026-08-13T02:34:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1372_commercial_truck_dealership_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T02:42:00.000Z

All checks pass. The PRD is complete.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/workspace/PRD.md` — 367 lines.

**Section overview:**
- **§1 Introduction** (2 paragraphs): business framing around three clocks (build calendar, floor-plan interest, downtime commitment) and the two design commitments (scarce contested pools, ledger-derived money).
- **§2 Global Specifications** (11 subsections): RBAC with per-role identity translation (FleetCustomer entity-backed; nine opaque operator roles); the fixed verbatim §2.2 response envelope; pagination (`limit` default 10/min 1/max 100, `offset` default 0, `created_at` ascending); the logical clock (startup default `2026-08-01T00:00:00Z`, monotonic advance); common resource properties including the `FloorPlanEntry` exception (no `updated_at`/`version`); integer-cents/half-up precision and the 360-day year; both OCC rules (`expected_customer_account_version`, `expected_unit_version` → `ERR_STALE_VERSION` 412); the five-entry-type floor-plan ledger invariant and replay order; the `open_ar_cents`/credit-hold posture model; the full 22-priority validation order; and the daily ops sweep contract including its eight tally output keys and one-promotion-per-order-per-run rule.
- **§3 Business Logic** (9 subsections, organized by dealership department workflow): accounts/tiers; build-slot pools and factory orders (full pinned pricing sequence with chassis/engine/axle constants, loyalty tiers, 1.08 SEVERE multiplier, 285,000¢ destination fee, provisional-vs-committed snapshots); units (inspection loop with `recondition_count`, aging bands with day-90/180/181 boundaries, interest accrual vs payoff-quote dual variants, sell/wholesale payoff sequences); trade appraisals (BOOK vs MARKET variants, ceiling discipline, 10-day offer expiry); service resources and booking (half-open bay vs closed travel-buffered mobile overlap semantics, 60-minute no-show grace); repair orders (two independent state dimensions, demotion check); totals and downtime penalty (pinned evaluation order, 120-minute grace, 25% rate, 50% labor cap); warranty claims (SoD, three adjudication outcomes, four-level cascade into RO/account, appeal loop, write-off 2,500¢/45-day rule); parts counter (per-line rounding pinned, 40% discount cap, 15% restocking fee after 30 days).
- **§4 Endpoint table:** all 80 endpoints, 4 columns each, "all roles" compression for the uniformly-authorized GET endpoints.
- **§5 Error catalogue:** all 53 error IDs with HTTP statuses, 2 columns.

**Hard-contract results:**
- Contract 1 (field coverage): 121 entity fields + 71 request-body + 21 query params — all present after one repair (`entry_type` was initially named only via its five enum values; fixed by naming the field in §2.8). PASS.
- Contract 2 (rule coverage): 22 validations (with priority ordering in §2.10), 2 OCC rules, 57 state transitions, 10 calculations with all constants embedded in prose, all endpoint side effects — expressed. PASS.
- Contract 3 (§3 path purity): 618 backticked tokens scanned in §3 — zero path/method violations. PASS.

**Scaffold-coverage gaps detected:** none remaining; the only gap found during verification (missing literal field name `entry_type`) was repaired in-place.

## Step 5: Generate Unit Tests — 2026-08-13T03:12:30.000Z

All artifacts are generated and audited. Here is the summary.

## Files written

**`test_helpers/` (Stage 1)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/test_helpers/`:
- `types.py` — 15 TypedDicts (FloorPlanEntry correctly omits `updated_at`/`version`) + 17 enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 60 PRD §4 endpoints
- `api_errors.py` — 55 `ApiErrorId` entries with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — 15 per-entity assertions + `assert_ledger_invariant` (signed-sum ledger rule)
- `factories.py` — payload factories with unique VIN/SKU/bay-code generators
- `constants.py` — PRD thresholds (destination fee, APR 690bp, grace 120 min, qty-break 10, write-off 2500/45d, etc.)
- `test_users.py` — `TEST_USERS` for all 10 roles + `make_fleet_customer_headers` (entity-backed), `make_warranty_admin_headers`, `make_oem_adjudicator_headers` (SoD anchors)
- `fixtures.py` — composite chains: `create_new_unit`/`create_ready_unit` (pool→order→commit→build-cycle sweeps→receive), `drive_ro_to_invoiced`, `create_submitted_claim`, `offer_appraisal`, clock/sweep helpers
- `__init__.py` — barrel export (framework + PRD-specific); imports verified

**`test_suite/` (Stage 2)** — `conftest.py` + 10 test files (`test_01_envelope_pagination_clock` … `test_10_validation_and_security`), 99 tests total.

## Test counts per source queue

- **Queue A (§1.8 Difficulty): 44 tests** — all 22 instances covered with exactly ≥2 tests each
- **Queue B (§1.9 Corner): 55 tests** — all 55 non-stub instances covered with ≥1 test each; 9 `excluded_because` stubs correctly not translated

## Instances skipped

None. Every non-stub instance passed the PRD-first two-condition filter.

## Deviations / findings

1. **Design-yaml arithmetic error corrected (PRD-first)**: `Corner/cross_cutting/occ_stale_version_rejected_on_floorplan_adjustment` precomputes the 5-day interest as 9663 (balance 10094663), but the PRD §3.3 formula yields `round_half_up(10085000·690/10000/360·5)` = **9665** (balance 10094665). The yaml's own final value (10095665) is only consistent with 9665, confirming a typo. The test asserts the PRD-derived 9665/10094665/10095665. All other precomputed literals in both indices were recomputed and match the PRD formulas.
2. **Two sub-assertions dropped as non-PRD-derivable** (instances still tested on their PRD-pinned claims): `customer_account_creation_defaults_applied`'s literal `version == 1` (PRD §2.5 never pins the initial version) and `floorplan_entry_immutable_no_update_endpoint`'s "no PATCH endpoint exists" (undefined-route behavior is not a PRD contract; the test asserts the append-only entry shape per §2.5 instead).
3. **Stub cross-reference quirk (reported, not translated)**: three `errors`-section stubs (`error_writeoff_covered`, `error_clock_regression_covered`, `error_stale_version_covered`) carry `difficulty_instance` pointers that name §1.9 corner instances rather than §1.8 difficulty instances. The pointed-at instances exist and are covered by real tests, so the error ids are exercised regardless.

## Design-tag audit result

- 99/99 tests carry exactly one `Design:` line as the final docstring line; every tag resolves to a real instance name in the source yaml; no untagged, dual-tagged, or dangling tags.
- Coverage audit: zero shortfalls in both queues (22 difficulty × ≥2; 55 corner non-stub × ≥1).
- PRD-citation audit: programmatic verbatim check — every cited sentence (≥8-word fragments) survives literal grep of `PRD.md`; 0 failures. No `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate Implementation — 2026-08-13T03:16:00.000Z

Implementation complete and verified. The server boots cleanly from a fresh process on the default port, the store starts empty, and the envelope matches the scaffold.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/workspace/implementation/`)

- `start.sh` — guarded dependency install (`python3 -c "import flask"` check), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — app factory, blueprint registration, `ApiError`/HTTP/generic exception handlers → error envelope
- `db.py` — in-memory `Store` (dicts keyed by id, starts empty, no seeding), logical clock starting `2026-08-01T00:00:00Z`, id/timestamp/stamp/touch helpers
- `errors.py` — `ApiError` + constructors for the scaffold error ids
- `response.py` — `meta`/`response_type`/`data` envelope; pagination fields (`limit`/`offset`/`total_count`/`has_more`) inside `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` validation + role gating (10 declared roles)
- `helpers.py` — body/field validators, ISO datetime/date/build-month parsing, pagination (limit default 10 clamped [1,100], offset ≥ 0), created_at-asc sort, filters
- `services.py` — all calculations: factory-order tiered pricing, per-line parts pricing, RO totals in pinned dependency order, downtime penalty, floor-plan interest/payoff, aging/curtailment, book/market trade allowance, credit posture, slot posture, upfit compatibility, claim cascade (L2–L4), booking demotion
- `serializers.py` — one explicit serializer per entity
- `routes/` — `ops.py` (clock + sweep), `accounts.py`, `slots.py`, `orders.py`, `units.py`, `appraisals.py`, `resources.py` (bays + mobile units), `repair_orders.py`, `lines.py`, `bookings.py`, `claims.py`, `parts.py`

## Endpoint count

All **80** endpoints from the PRD §4 table are implemented (2 ops, 4 accounts, 3 slots, 9 orders/upfit/commit/re-hold/cancel/receive, 9 units incl. ledger/curtailments/adjustments/payoff-quote, 7 appraisals, 8 bays/mobile, 12 repair orders, 3 RO lines, 5 bookings, 9 warranty claims, 13 parts/sales/sale-lines).

## Verification

Exercised ~140 assertions across five fresh-boot smoke runs covering: auth/role errors, OCC 412s, slot pool lock/exhaust/close, hold expiry and re-hold, commit/cancel with 2% fee → CREDIT_HOLD cascade, receive → ADVANCE ledger, sweep interest accrual (stocking_date/created_at order), payoff projection vs actual accrual divergence, inspect/recondition loop, sell/wholesale with interest-then-PAYOFF, upfit incompatibility/dependency, booking overlap (bay half-open adjacency allowed, mobile closed-interval buffer touch conflicts), operating-hours and out-of-service checks, two-dimension RO lifecycle, downtime penalty boundary (exactly 120 min = 0, 121 min = nonzero), invoice credit check (402) and account-hold check (409), warranty submit/adjudicate/appeal/close/pay/write-off incl. segregation-of-duties and the AR cascade on adjudication, parts tier+qty-break per-line rounding, restocking fee after 30 days, and pagination meta. Every observed mismatch during testing was traced to an arithmetic/assumption bug in my scratch test scripts, not the implementation (each re-derived against the PRD formula).

## PRD ambiguities resolved

1. **`api_request_timestamp` / entity `created_at` source clock** — stamped from the logical clock (not wall time) for full determinism; `created_at`/`updated_at` always use 3 fractional digits per §2.5; other datetimes (`hold_expires_at`, `start_at`, `current_utc`, …) serialize without a fractional part when zero so clock inputs like `"2026-08-15T00:00:00Z"` echo back verbatim.
2. **`units_rebucketed` tally** — counted as units whose computed `aging_bucket` changed since creation/last sweep (a private `_sweep_bucket` marker; not serialized, no version bump), since aging is otherwise a pure function of the clock and would always tally 0.
3. **Duplicate slot pool `(build_month, vocation_group)`** — PRD §3.2 maps it to `ERR_INVALID_REQUEST`; §2.10 item 9 groups it under a "(409)" label but the §5 catalog fixes `ERR_INVALID_REQUEST` at 400 → returned **400** per the catalog.
4. **Ownership vs existence ordering** (FleetCustomer counter/accept/decline, adjudication SoD) — path-id existence (404) is checked before the ownership/SoD 403, since the ownership check requires the resource; ownership/SoD then precedes body and state checks per §2.10 priorities 3 < 4 < 7.
5. **Upfit-lines endpoint check order** — per §2.10, full-set upfit compatibility (priority 8) runs before the spec-freeze check (priority 10), so an incompatible code against a COMMITTED order returns 422, not `ERR_SPEC_FROZEN`.
6. **Booking `travel_minutes` default** — PRD §3.5 ("travel buffer defaults to zero") wins over the `MobileServiceUnit.default_travel_minutes` field description ("applied to bookings"); the unit default is stored but not applied.
7. **VIN uniqueness scope** — enforced only at factory-order `receive` (the scaffold's `applies_to` for `ERR_DUPLICATE_VIN`), not at appraisal accept; no 17-char length enforcement (not in the §2.10 body checks).
8. **Write-off** — no covered/AR cascade on write-off (state machine lists none), even though `WRITTEN_OFF` drops the claim from future `warranty_covered_cents` recomputations.
9. **PAYOFF posting** — at sell/wholesale, interest accrues only when days elapsed > 0 and balance > 0; the PAYOFF entry posts only when the post-accrual balance is nonzero (avoids a 0-amount ledger line); USED units post nothing.
10. **Pagination out-of-range params** — `limit`/`offset` are clamped to [1,100]/[0,∞) rather than rejected (PRD declares ranges but no error).

## Step 7: Run Tests and Iterate — 2026-08-13T03:26:00.000Z

Two consecutive clean 8-round sweeps: 99/99 × 8 = 792 test-pass instances, zero failures. The earlier booking-cancel flake is gone.

## Summary

- **Iterations run:** 2 (one initial sweep that surfaced 4 failing tests; 3 test fixes applied; 2 consecutive clean confirmation sweeps of 8 rounds each, 99/99 each round).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**

  1. `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/test_suite/test_08_warranty_claims.py` — `test_warranty_writeoff_window_and_small_balance_rules`. The test was computing residual as `claimed - approved` (2000) but PRD §3.8 verbatim defines residual as "approved total minus `paid_cents`" (= 78000 with no payment posted). Added a `post_claim_payment(75500)` call so residual = 2500 ≤ 2500, making the small-balance branch reachable per the PRD definition.

  2. `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/test_suite/test_09_parts_counter.py` — `test_insufficient_stock_and_discontinued_part`. Setup put the part at `on_hand=0` before discontinuing, so a follow-up sale triggered both `ERR_INSUFFICIENT_STOCK` and `ERR_PART_DISCONTINUED` — PRD §2.10 priority 14 lists both at the same level with no stated tie-breaker (error-precedence silence). Changed initial `on_hand` 3→4 so `on_hand=1` at discontinue time, making `ERR_PART_DISCONTINUED` the only rule that fires.

  3. `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/test_suite/test_10_validation_and_security.py` — `test_duplicate_vin_and_sku_rejected`. Two consecutive `create_shipped_order()` calls used the same default `receive_date="2026-08-15T00:00:00Z"`; the second `set_clock` to the same timestamp violated PRD's "must be strictly after the current clock" rule (`ERR_CLOCK_REGRESSION`). Passed `receive_date="2026-08-16T00:00:00Z"` for the second order.

- **Fixes applied to `implementation/`:** None. The implementation was PRD-faithful in all four cases; all failures traced to test/test-setup bugs.

- **Flakiness note:** Round 1 also reported `test_booking_cancel_demotes_ro_scheduled_to_open` failing on per-test server-restart ("could not be restarted"). That was a transient infrastructure timeout under 8-way parallel load, not a test or implementation defect; it has not recurred in the subsequent 16 rounds (2 clean sweeps × 8 rounds each).

## Step 8: Finalize PRD — 2026-08-13T03:29:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/workspace/PRD_FINALIZED.md` written.

## Line counts
- PRD.md: 366 lines; PRD_FINALIZED.md: 366 lines; delta 0 lines / 0.0% (one in-place sentence appended to an existing line — no lines added or removed).

## Changes (1 total)
- **§2.10 (Validation Order, priority 14)** — **revise** — appended tie-breaker sentence: "Within this level, when a part fails both stock sufficiency and active status, the stock check is evaluated first and `ERR_INSUFFICIENT_STOCK` is returned." — impl: `implementation/routes/parts.py:114-120` (parts sale) and `implementation/routes/lines.py:58-63` (RO part-line add), both of which check `on_hand < qty` before `status != ACTIVE`.

## Items requiring no edit (2)
- **Item 1 (test_08 warranty write-off residual):** pure test bug. PRD §3.8 already pins residual as "approved total minus `paid_cents`" verbatim, and impl `implementation/routes/claims.py:223` computes exactly `residual = _approved_total(c) - c["paid_cents"]`. PRD already determines behavior; prose kept verbatim.
- **Item 3 (test_10 clock regression):** pure test fixture bug (two `set_clock` calls to the same timestamp). PRD §2.4 already pins "must be strictly after the current clock value … `ERR_CLOCK_REGRESSION`", and impl `implementation/routes/ops.py:21-23` enforces `target <= store.clock → ERR_CLOCK_REGRESSION`. PRD already determines behavior; prose kept verbatim.

## Per-edit pre-edit search log
**Edit 1 (§2.10 item 14 tie-breaker):**
- (a) **Subject:** relative evaluation order of part stock-sufficiency vs part active-status checks when both fail on the same part.
- (b) **Impl paths enumerated** (via grep for `INSUFFICIENT_STOCK`/`PART_DISCONTINUED` plus a full grep for every `on_hand`/`DISCONTINUED` touchpoint): (1) `parts.py:113-120` `create_sale` — per-line loop over all parsed lines before any decrement; within each line, stock checked first, then active status; (2) `lines.py:54-65` `create_line` — single PART line, stock first, then active status; (3) `parts.py:74-82` `discontinue_part` — status flip only, no stock interaction; (4) `parts.py:206-254` `return_sale_line` — restores `on_hand`, never checks stock/discontinued; (5) `parts.py:26-52` `create_part` — initializes `on_hand`, no checks; (6) `claims.py:41-53` `create_claim` — the `ERR_INVALID_REQUEST` claimed-amount check sharing priority 14, which never touches part stock/status. All paths read directly.
- (c) **Wording adjustment:** scoped the sentence to the stock-vs-active-status pair only ("when a part fails both …"), so it (i) covers both the single-line RO-line site and the per-line parts-sale site identically, (ii) makes no claim about cross-line ordering in multi-line sales (impl validates lines in request order — a silence Step 7 did not surface, left untouched per hard scope), and (iii) leaves `ERR_INVALID_REQUEST`'s position within level 14 undisturbed, consistent with `claims.py`.

## Step 9: Complete PRD — 2026-08-13T03:39:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1372_commercial_truck_dealership_service/workspace/PRD_COMPLETED.md` written as a minimal patch over PRD_FINALIZED.md.

**Stats**: PRD_FINALIZED.md 366 lines / 57,415 chars → PRD_COMPLETED.md 367 lines / 64,571 chars (+1 line, +7,156 chars; 44 lines touched, all in-paragraph). Counts: 37 ambiguity-pins (insert), 5 mismatch-revisions (revise).

Changes, by PRD section:

- §2.1 — revise — mismatch — header rejection also fires on empty `X-User-ID`, not only missing — implementation/middleware.py:26
- §2.2 — insert — ambiguity — parts-sale-line return is the noted exception returning the sale line, not the sale — implementation/routes/parts.py:254
- §2.2 — insert — ambiguity — `has_more` defined as offset+page-size < total_count — implementation/helpers.py:186
- §2.2 — insert — ambiguity — `response_type` values pinned per endpoint kind — implementation/response.py:17-27
- §2.3 — revise — mismatch — limit/offset are clamped (1–100, ≥0, unparseable→default), not range-rejected — implementation/helpers.py:174-188
- §2.4 — revise — ambiguity — equality-to-now clock set is a regression (strictly-after) — implementation/routes/ops.py:21-23
- §2.4 — insert — ambiguity — datetime parsing: Z/offset normalized to UTC, naive = UTC, bare date = midnight — implementation/helpers.py:113-125
- §2.5 — insert — ambiguity — id is RFC 4122 UUID string; `version` starts at 1 — implementation/db.py:36-37, 82-90
- §2.5 — insert — ambiguity — business-instant fields render whole-seconds vs 3-fractional-digits conditionally; date fields `YYYY-MM-DD`; nullables render `null` — implementation/db.py:44-67, serializers.py passim
- §2.8 — insert — ambiguity — ledger tie-break is created_at ascending = posting order — implementation/routes/units.py:182-184
- §2.9 — insert — ambiguity — automatic hold/clear only replaces ACTIVE↔CREDIT_HOLD, never a CLOSED account — implementation/services.py:77-86
- §2.10 #4 — insert — ambiguity — within level 4, errors surface in documented field order — implementation/routes/*.py field-parse sequences
- §2.10 #10 — insert — ambiguity — on upfit-line append, compatibility (8) is evaluated before spec-freeze (10) against the full resulting line set — implementation/routes/orders.py:128-134
- §2.11 — revise — ambiguity — sweep pinned to fixed 8-step order incl. SLA watch; reached = lapsed for holds and offers; no-show strictly >60 min; hold expiry fires even with missing pool; `units_rebucketed` counts moves since baseline; `orders_expired` includes pool-close expiries; per-set order: units stocking_date+created_at, others created_at — implementation/routes/ops.py:28-149
- §3.1 — insert — ambiguity — patch fields optional, applied-as-given, version bumps even on no-op; manager-set status not re-evaluated against AR until next event — implementation/routes/accounts.py:61-87
- §3.2 (pools) — insert — ambiguity — CLOSED is absorbing (releases never reopen); LOCKED pool past month stays until sweep; month-end boundary defined (clock date ≥ first of next month) — implementation/services.py:69-72, 103-111
- §3.2 (create) — insert — ambiguity — `hold_expires_at` is exactly 14 days after the clock instant — implementation/routes/orders.py:21, 87
- §3.2 (append) — insert — ambiguity — appended line re-runs full pricing incl. fresh loyalty snapshot; hold window not restamped — implementation/routes/orders.py:128-141
- §3.2 (commit) — insert — ambiguity — clock == hold_expires_at already lapsed; commit counter shift cannot reopen a LOCKED pool — implementation/routes/orders.py:144-164
- §3.2 (re-hold) — insert — ambiguity — re-hold runs no upfit re-validation and no price recompute — implementation/routes/orders.py:167-188
- §3.2 (receive) — insert — ambiguity — order-state check precedes VIN uniqueness — implementation/routes/orders.py:226-232
- §3.3 (inspect) — revise — mismatch — `recondition_count` increments on FAIL only, never on PASS — implementation/routes/units.py:70-74
- §3.3 (payoff) — insert — ambiguity — projection zero on non-floor-planned/non-positive units; bad as_of_date → ERR_INVALID_REQUEST — implementation/routes/units.py:188-209
- §3.3 (adjustment/curtailment) — insert — ambiguity — ADJUSTMENT works on any unit, amount may be zero, balance may go negative; curtailment ERR_INVALID_REQUEST on both excesses, state check first; neither moves `last_accrual_date` — implementation/routes/units.py:142-173
- §3.3 (sell) — insert — ambiguity — check order state→appraisal→buyer; sale never touches buyer AR — implementation/routes/units.py:97-118
- §3.3 (wholesale) — insert — ambiguity — READY check before aging-bucket check — implementation/routes/units.py:126-133
- §3.4 (book) — revise — mismatch — rounding order: depreciated book value rounded half-up first, then whole-mile penalty subtracted — implementation/services.py:308-316
- §3.4 (offer) — insert — ambiguity — `offer_expires_at` exactly 10 days after clock instant — implementation/routes/appraisals.py:104
- §3.4 (accept) — insert — ambiguity — clock == offer_expires_at rejects with ERR_APPRAISAL_STATE; accepted VIN not uniqueness-checked — implementation/routes/appraisals.py:129-155
- §3.5 (resources) — insert — ambiguity — open_hour 0–23, close_hour 1–24; set-status body field is `status` — implementation/routes/resources.py:26-29, 61-71
- §3.5 (booking create) — insert — ambiguity — no RO-state precondition (booking allowed even on cancelled RO); bay window anchored to start's day, end==close in bounds — implementation/routes/bookings.py:25-30, 74-76
- §3.5 (overlap) — insert — ambiguity — each mobile booking expands by its own stored `travel_minutes` — implementation/routes/bookings.py:45-58
- §3.6 (create) — insert — ambiguity — external_vin needs no inventory presence — implementation/routes/repair_orders.py:34-41
- §3.6 (lines) — insert — ambiguity — labor `hours` is numeric, not necessarily integer; line-add recomputes only the raw sums — implementation/routes/lines.py:30-33, 83
- §3.6 (revise) — insert — ambiguity — non-DECLINED auth also yields ERR_RO_STATE — implementation/routes/repair_orders.py:130-135
- §3.6 (booking/scheduling) — revise — mismatch — any booking moves OPEN→SCHEDULED (not only the first); complete-work recomputes §3.7 totals — implementation/routes/bookings.py:126-128, repair_orders.py:163-181
- §3.6 (cancel) — insert — ambiguity — cancel gated only on work_status, auth state not consulted — implementation/routes/repair_orders.py:229-238
- §3.6 (invoice) — insert — ambiguity — totals computed before the fiscal guards so the credit test uses the true due — implementation/routes/repair_orders.py:188-201
- §3.6 (payment) — insert — ambiguity — work_status checked before amount equality — implementation/routes/repair_orders.py:215-220
- §3.7 — insert — ambiguity — downtime-penalty cap uses `labor_sum_cents` current at completion — implementation/services.py:268-274
- §3.8 (draft) — insert — ambiguity — claim drafting needs no RO state, only existence — implementation/routes/claims.py:31-71
- §3.8 (adjudicate) — insert — ambiguity — SoD comparison fires on equality with stored submitter (null never matches); outcome body parsed before claim-state check — implementation/routes/claims.py:113-129
- §3.8 (deny/appeal) — insert — ambiguity — DENY fires no cascade — implementation/routes/claims.py:147-152
- §3.8 (payment) — insert — ambiguity — claim payment does not re-run the covered/AR cascade; write-off aging is strictly >45 days — implementation/routes/claims.py:197-232
- §3.9 (catalog) — insert — ambiguity — parts list supports a `status` filter — implementation/routes/parts.py:55-62
- §3.9 (sale) — insert — ambiguity — buyer account status not consulted at the counter; all-line stock/active validation before any decrement; posting itself may trigger CREDIT_HOLD; embedded `lines` carry part_id/quantity only — implementation/routes/parts.py:87-163
- §3.9 (return) — insert — ambiguity — restocking fee itself rounded half-up, strictly >30 days (exactly 30 free); core charges never credited — implementation/routes/parts.py:206-254

Verified: all 39 error IDs raised by the implementation exist in the PRD §5 catalogue with matching HTTP statuses, and only the two OCC endpoints take expected-version fields.
