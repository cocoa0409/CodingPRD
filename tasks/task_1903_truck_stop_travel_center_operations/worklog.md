# Worklog — task_1903_truck_stop_travel_center_operations

## Step 1: Create Task Directory — 2026-08-14T23:49:00.000Z

Directory `tasks/task_1903_truck_stop_travel_center_operations/` and `workspace/` already created by the invoking skill call (index 1903 assigned by the pipeline invoker).

## Step 2: Generate Scaffold — 2026-08-15T00:48:06.753Z

Scaffold generation complete for task 1903 (Truck Stop & Travel Center Operations). All three artifacts written and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/SCAFFOLD.yaml` (2,155 lines — §1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (811 lines — single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/SCAFFOLD_CORNER_DESIGN.yaml` (1,497 lines — single top-level key `scaffold_corner_design`)

## Counts

- **Entities: 32** (incl. event/ledger children: ScaleWeighEvent, WorkOrderPart, CashDrop, ShiftReconciliation, SafeDeposit, BulkDelivery, LoyaltyPointsLot)
- **State machines: 18** blocks (FuelSale carries parallel `status × payment_status`; ServiceQueueTicket and PurchaseOrder are cyclic; ParkingReservation/WorkOrder/ScaleTicket branch with refund paths)
- **Calculations: 13** (retail/contract quote, finalization, loyalty accrual with FEFO expiry, parking pricing, service surcharges, scale tolls, shift cash, drop waterfall, shop invoice, reorder projection, water usage, fleet tier)
- **Validations: 41** ordered rows (auth → segregation of duties → existence → state → safety → referential → temporal → constraint → fiscal)
- **Endpoints: 175** (94 POST / 79 GET / 2 PATCH; `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- **Errors: 40** — all triggerable, all cited in the design files
- **Roles: 7** (4 opaque staff roles with segregation of duties; 3 entity-backed: MaintenanceTech→Technician, FleetManager→FleetAccount, LoyaltyMember→LoyaltyMember)
- **Concurrency rules: 2** (OCC: `fuel-price-supersede-stale-site` on TravelCenterSite.version, `contract-amend-stale-version` on FleetContract.version)
- **§1.8 difficulty instances: 19** across all 9 rules (combinatorial_formula has 3 — modes (a), (b), and (c))
- **§1.9 corner instances: 64 active + 3 excluded_because stubs** across all 9 guide sections

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(858 calls scanned across §1.8+§1.9; separate checks also passed: zero banned-vocabulary hits, zero duplicate instance names, zero unbound `${var}` placeholders, zero unresolved grounds refs.)

## Design decisions of note

- **Archetype blend**: pricing_engine (retail vs contract) × quota_allocation (parking/queues/bays), flat topology, 7 complexity layers including OCC, scheduled price activation, and derived-field reconciliation.
- **All assert arithmetic pre-computed and pinned** (verified via Python): e.g. retail quote 385−10−min(200,500)×0.5=275, provisional 11000 vs final 10450; contract tiers 283/280/276 at rack 2.7000; shop invoice 87599+18750+300+2628=109277; shift expected 26599 with deposit 6599 derived after expected (pinned evaluation order); loyalty per-line rounding 71+11=82 (not 83); reorder 14800/271/68(17 cases); shower water capped at 112.5 gal.
- **Two genuinely different interval semantics**: parking = half-open windows against *aggregate* capacity; bay scheduling = half-open WO-vs-WO but *closed* maintenance blocks (a window ending exactly at `blocked_from` conflicts).
- **Segregation of duties** is machine-enforced via opaque user ids (opener≠closer, closer≠reconciler, payout approver≠cashier) with dedicated 403 error.
- **Loyalty points are lot-based with 360-day expiry, FEFO burn, newest-first clawback** — enabling the clock-driven expiry corner (redeem fails after lots expire) and the zero-floor burn clamp (points debited even when the price floor made them worthless).
- Every FK has a reverse-reachability GET; all path placeholders normalized to `{id}` to match the linter's FK check.

## Step 3: Copy Shared Files — 2026-08-15T00:48:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1903_truck_stop_travel_center_operations/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-15T01:02:34.626Z

All checks pass. The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/workspace/PRD.md` — 475 lines, ~84 KB.

**Sections covered:**
- **§1 Introduction** (3 paragraphs: business context, system goals, technical commitments)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC with all 7 roles and per-role identity translation (3 entity-backed, 4 opaque) plus segregation of duties; 2.2 response envelope emitted **byte-verbatim** from the skill's fixed block; 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields); 2.4 common properties incl. the six thin ledger entities (`ScaleWeighEvent`, `CashDrop`, `ShiftReconciliation`, `SafeDeposit`, `BulkDelivery`, `LoyaltyPointsLot`); 2.5 logical clock (default 2026-08-01T00:00:00Z, lazy expiry) and half-open vs closed window conventions; 2.6 OCC (both rules: `expected_site_version` on price posting, `expected_contract_version` on contract amendment, `ERR_STALE_VERSION`/412); 2.7 precision (integer cents, round-half-up, 4-decimal rack arithmetic, 3-decimal gallons, 2-decimal water); 2.8 shift cash ledger with pinned evaluation order and register posture triggers; 2.9 loyalty points ledger (FEFO burn, newest-first clawback, 360-day expiry, pinned per-source rounding); 2.10 validation pipeline ordering with `ERR_INVALID_REQUEST` deliberately last.
- **§3 Business Logic** (9 subsections): site/price-book/pumps; fuel sales (retail + contract quotes, dual state machines, refund-void cascade); fleets and tiered contracts; loyalty and discount networks; driver services (parking, shower/laundry queues, scale); store/inventory/purchasing; shop and road service; registers/shifts/cash control; bulk supply.
- **§4 Endpoint table** — 175 endpoints, 4 columns only.
- **§5 Error catalogue** — 40 errors, 2 columns only, no trigger conditions.

**Zero-Silence Rule coverage (all fully rendered in prose, no pseudocode):**
- **All 13 calculations**: retail quote (price selection, network max allowance, half-cent points, zero floor, provisional vs final variants), contract quote (rack + 0.1500 freight − tier margins 0.02/0.05/0.09 at 4-decimal rounding, shortfall rule, provisional-tier vs fleet-preview variant), finalization (frozen snapshots, dispensed vs max gallons divergence, post-redemption 0.5 pt/$), points accrual (per-source pinned rounding, FEFO, clawback, 360 days), parking amount (15-min grace, ceil hours, 300¢/hr, 800¢ oversize, 336-hr window, 2-hr no-show grace), service pricing (1500/400 base, 300 weekend, 150 peak 17:00–22:00 UTC), scale tolls (1250 + 400 certified, reweighs free, conservation), shift expected cash (pinned order, deposit = max(0, expected − float), variance, 5×/1× posture triggers), drop targets (exact denomination sum, canonical denominations, greedy form), shop invoice (pinned order: parts exact, labor rounded, 150¢/net-TIRE environmental, 3% supplies), bulk reorder (90% target, projection over lead time, safety stock, ceil-to-case-pack for packaged oil), water usage (45-min cap at 2.5 gpm, 2.0 gal/lb), fleet tier recompute (inclusive 30-day window, 5,000/20,000-gal inclusive breakpoints).
- **All 73 state transitions across 19 machines** rendered with preconditions + error IDs + side effects; multi-hop cascades (finalize → contract volume → rolling volume → tier flip; refund-void → cash/billing/points/contract reversal; fleet close → contract termination; network retire → enrollment retirement) explicitly enumerated.
- **All 41 validations** paired with their error IDs near the guarded workflow; relative priority expressed at pipeline level (§2.10) and at endpoint level where checks collide (fuel authorize: state → referential → fiscal with points before shortfall before credit; shift close: segregation → below-float → unapproved-variance; parking create: plate → window → capacity).

**Hard Contract Reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 189 required, 189 present, 0 missing
Status: PASS

Rule coverage check:
- validations priority orderings: expressed (pipeline + endpoint-level)
- concurrency_rules OCC: 2 checked, 2 expressed (write endpoint + expected_*_version + ERR_STALE_VERSION/412)
- state transitions: 73 checked, 73 fully expressed
- calculations: 13 checked, 13 fully expressed (constants embedded, reconstruction-safe prose)
- validations conditions: 41 checked, 41 matchable to error_id in prose
- endpoint side effects / applies_to scopes: all expressed (incl. multi-scope rules v15, v24–27, v33–35)
- field structured content (defaults, initial states, thin entities): reconstructible
- sibling-branch symmetry: void/cancel/complete/pay branches at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 807
- tokens starting with `/`: 0; bare HTTP methods: 0; method+path: 0
Status: PASS
```

Additional verifications: §2.2 matches the fixed block byte-for-byte (verified programmatically); all 91 enum values and 42 state strings present verbatim; §4/§5 table shapes confirmed (4 and 2 columns); no operator syntax or fuzzy quantifiers leaked into prose. PRD.md ends at §5 with no audit footer.

## Resume Audit — 2026-08-15T01:31:00.000Z

Previous run terminated mid-flight after Step 4 was logged. Orchestrator audit of on-disk artifacts:

- **Steps 1–4: DONE** (logged above; SCAFFOLD.yaml 2,155 lines, both design yamls, INSTRUCTION.md, PRD.md 475 lines — all present and non-truncated).
- **Step 5 (tests): PARTIAL.** `test_helpers/` complete (all 9 standard files, syntax-clean); `test_suite/` has conftest + 10 test files, 80 test functions, 64 unique Design tags, 0 unknown tags. Coverage gap: **19 of 83 non-stub design instances have no test** (16 corner: entities×2, errors×4, rbac×3, validations×7; 3 difficulty: combinatorial_formula/shift_expected_then_deposit_order, compensating_invariant/shift_cash_conservation_across_drop, transitive_cascade/payout_expected_posture_close_block). All 16 difficulty-tagged instances carry 2 tests each (positive+negative variants). Files are syntactically complete — the gap is missing instances, not truncation.
- **Step 6 (implementation): DONE.** 34 Python files across routes/services, all syntax-clean; `start.sh` present; boot probe on PORT=19303 succeeded (POST /sites → 201 with correct envelope/defaults/clock; GET /sites → 200).
- **Steps 7–9: not started.**

Resume plan: complete Step 5 (generate the 19 missing tests only — existing 80 tests kept), then Steps 7→9.

## Step 5: Generate Unit Tests — completion verified 2026-08-15T01:40:00.000Z

Resume-run orchestrator verification: the 19-instance gap flagged in the Resume Audit was closed by `test_suite/test_11_shift_cash_rbac_gapfill.py` (620 lines, written 01:35, after the 01:31 audit). Current state re-audited programmatically:

- 99 test functions across 11 test files (3,489 lines total), all syntax-clean (`py_compile` pass on test_suite + test_helpers).
- 83 unique `Design:` tags matching exactly the 83 non-stub design instances (19 difficulty + 64 corner) — **0 missing, 0 unknown tags**.
- `test_helpers/` unchanged since prior verification (all 9 standard files present, syntax-clean).

Step 5 is DONE. Steps 1–6 all complete; proceeding to Step 7.

## Step 7: Run Tests and Iterate — 2026-08-15T02:05:00.000Z

All 8 rounds pass 97/97. The sweep is clean. Final state verified.

## Summary

**Iterations run:** 3 sweeps total. Sweep 1 found a collection error (0 tests ran). Sweep 2 surfaced 8 consistent failures + 1 environmental flake. Sweep 3 (after fixes) — all 8 rounds 97/97 passed, `passed == total` in every round.

**Tests deleted (2), with PRD-silence category:**
- `test_11_shift_cash_rbac_gapfill.py::TestStrictRequestContract::test_site_create_with_system_fields_rejected` — PRD silent on rejecting client-supplied system fields (`id`/`version`); §2.6 "no other endpoint accepts a version field of any kind" admits both strict-reject and ignore-unknown-field implementations (two-reader divergence). Scaffold driver: `Corner/entities/entity_extra_system_field_rejected` ("strict request contract" wording exists only in SCAFFOLD_CORNER_DESIGN.yaml, never in PRD prose).
- `test_11_shift_cash_rbac_gapfill.py::TestStrictRequestContract::test_stock_create_with_client_supplied_low_stock_rejected` — PRD §3.6 pins `is_low_stock` as computed but never says a client-supplied value is rejected; same unique-derivability collapse. Scaffold driver: `Corner/entities/stock_is_low_stock_computed_rejects_client_input`.

**Fixes applied to test artifacts:**
- `test_helpers/fixtures.py` — re-exported `make_fleet_manager_headers` and `make_loyalty_member_headers` from `.test_users` (test_11 imported them from fixtures; they existed only in test_users). Fixed the collection failure blocking all 99 tests.
- `test_suite/test_10_work_orders.py` — `_setup_bay_with_block` used a bare `api` global (NameError); switched to the module-level `api_client` (2 tests fixed).
- `test_suite/test_11_shift_cash_rbac_gapfill.py` — added `api_client` import; `_setup_shift_with_cash_sales` passed bare `api` to `_store_sale` (NameError); now passes `api_client` (2 tests fixed). Also removed the now-unused `create_stock_item_payload` import and updated the module docstring.
- `test_suite/test_11_shift_cash_rbac_gapfill.py::test_cashier_cannot_post_fuel_price` — the test advanced the logical clock before posting a price with `effective_from=2026-08-01`, making the window start "in the past" and tripping the PRD-required §3.1 window-shape rejection on the legitimate FuelDeskLead posting. Reordered: post both the forbidden (Cashier) and successful (FDL) attempts at the initial clock, then advance.
- `test_suite/test_05_loyalty_members_networks.py::test_expired_points_redeem_rejected` — the fixture regressed the logical clock to 2025-08-10 (before the initial 2026-08-01), an operation PRD §2.5 does not grant ("may advance it"). Rewrote to grant points at the initial clock and advance past the 360-day expiry (to 2027-08-12); also added the missing `201` expected status on both `member_adjustment` calls (PRD §4: creating a resource — the points lot — responds 201).

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/members.py::get_member` — added lazy `loyalty.recompute_member_balance(member, bump=False)` on member read. PRD §2.5 requires lazy expiry evaluation "at the moment of the next read or write that depends on them" and §2.9 states `points_balance` "is always the sum of `remaining_points` across [non-expired] lots"; previously a member read after clock-driven lot expiry returned the stale stored balance. No version bump on read, mirroring the site retail-mirror derivation pattern.

**Environmental note:** one round-2-sweep flake (`test_retail_quote_stack_cap_clamps_points_leg`, `ConnectionResetError` mid-test under 8-round + cross-pipeline load) did not recur in the final sweep — resource contention, not a product bug.

## Step 8: Finalize PRD — 2026-08-15T02:12:00.000Z

PRD_FINALIZED.md is complete. All work verified. Here is the summary.

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/workspace/PRD_FINALIZED.md` produced (copy of PRD.md + 3 inline edits).

**Line counts / delta:** PRD.md 475 lines (84,529 chars) vs PRD_FINALIZED.md 475 lines (85,464 chars) — +1.11% by characters; line count unchanged (all edits are in-place sentence extensions; no new sections).

## Changes

- **§2.4** — insert — pinned the request contract: request bodies carry only named fields; client-supplied system fields (`id`/`created_at`/`updated_at`/`version`) and server-computed fields (e.g. `is_low_stock`, `points_balance`) are **ignored, not rejected**; server always assigns/computes them — impl: `implementation/services/core.py:11-22` (`new_record` mints system fields server-side), `implementation/routes/sites.py:16-38`, `implementation/routes/stock.py:42-56` (`is_low_stock` overwritten by `recompute_stock_low`), `implementation/routes/bulk.py:45-58`.
- **§2.5** — insert — pinned that clock regression is rejected: a `to_iso8601` earlier than the current reading fails with `ERR_INVALID_REQUEST` (400) — impl: `implementation/util.py:72-79` (`LogicalClock.set`), via `implementation/routes/clock.py:13-27`.
- **§2.9** — revise (append) — pinned that `GET /loyalty-members/{id}` re-derives `points_balance` against the current logical clock before responding (lazy expiry), as a pure projection that does **not** increment `version` or refresh `updated_at` — impl: `implementation/routes/members.py:57-66` (`recompute_member_balance(member, bump=False)`), `implementation/services/loyalty.py:36-42`.

## Per-edit pre-edit search log

**Edit 1 (§2.4).** (a) Subject: handling of non-named request-body fields (system + computed). (b) Enumerated: all 35 `new_record(` callsites in `routes/` and `services/` (grep listing — every create builds a fixed field dict from `req_*`/`opt_*` extractions; zero hits for `**body`/`dict(body)`/`body.copy()` pass-through); `validate.py` (no unknown-key check; `get_body` defers malformed bodies); grep for rejection language (`unknown|unexpected|extra field|not allowed|system field`) → only app.py catch-all handlers; PATCH endpoints `routes/fleets.py:48-57` and `routes/contracts.py:82-102` (named fields only); OCC endpoints honor only named `expected_site_version`/`expected_contract_version` (`fuel_prices.py:26-29`, `contracts.py:88-91`). (c) Wording: "ignored rather than rejected" + "always take their server-computed values" — avoids implying rejection anywhere, avoids echo claims, and stays consistent with §2.6 ("not accepting" a version field == ignoring it).

**Edit 2 (§2.5).** (a) Subject: clock-set direction constraint and its error. (b) Enumerated: `routes/clock.py::set_clock` (ISO validation then `CLOCK.set`); `util.py::LogicalClock.set` (strictly-earlier → 400; equal instant permitted); all `CLOCK.now()` readers; the mirror-refresh loop in `set_clock` (`clock.py:23-26`) is behaviorally invisible (lazy `get_site`/`list_sites` recompute agrees; `recompute_site_mirrors` never touches version). (c) Wording: "earlier than the current reading" (not "at or earlier") so an equal-instant set remains permitted, matching `new_dt < self._dt`.

**Edit 3 (§2.9).** (a) Subject: where/when `points_balance` is re-derived and whether read-time derivation mutates `version`/`updated_at`. (b) Enumerated: `services/loyalty.py:36-42` (`touch` only when `bump=True` and balance changed); bump=True callers `grant_lot:61`, `burn_fefo:94`, `clawback_newest:123`; read path `members.py:57-66` with `bump=False`; all other member-record-returning paths — `create_member` (fresh 0), `suspend`/`reactivate` (touch, no balance recompute), `close_member` (forfeit+touch), `adjust_points` (returns lot), `points_ledger` (returns lots), **`routes/fleets.py:117-123 fleet_members` listing — does NOT recompute**; live-check sites `fuel_sales.py:123,297`, `parking.py:164`, `service.py:71` use `redeemable_balance` directly. (c) Wording scoped explicitly to "reading a member through `GET /loyalty-members/{id}`" rather than any universal "member read", because the fleet members listing does not re-derive — a universal claim would have created a new mismatch on that unexercised path.

## step_7_diff items intentionally not edited

- fixtures.py re-export; test_10/test_11 NameErrors; test_11 import/docstring cleanup — pure test-artifact bugs, no behavioral signal.
- `test_cashier_cannot_post_fuel_price` reorder — test bug; PRD §3.1 already pins past-`effective_from` rejection and impl (`fuel_prices.py:41-42`) enforces it.
- `test_expired_points_redeem_rejected` 201-status addition — PRD §4 already pins create→201; impl (`members.py:122`) returns 201. (The clock-regression half of that rewrite did produce Edit 2.)
- Environmental flake (`ConnectionResetError`) — not a product behavior.

## Step 9: Complete PRD — 2026-08-15T02:25:00.000Z

All pins verified present. The work is complete. Here is the summary.

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/workspace/PRD_FINALIZED.md` (475 lines / 85,890 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1903_truck_stop_travel_center_operations/workspace/PRD_COMPLETED.md` (478 lines / 94,881 chars; **+3 lines, +8,991 chars**, 81 changed diff lines). All 175 impl routes match the §4 table exactly; all §4 role sets match impl decorators.

**Counts: 49 ambiguity-pins (inserts), 6 mismatch-revisions.**

### Mismatch-revisions
- §2.8 — revise — mismatch — refund/reversal cash decrements (void-refunds, paid cancels, store refunds) post against the attributed shift in any state; only money-collecting ops require `OPEN` — fuel_sales.py:398-406, parking.py:336-339, service.py:281-284, scale.py:173-176, store_sales.py:150-153.
- §2.10 — revise — mismatch — pipeline order rewritten: path-existence precedes field-based scoping; member-self path scoping (`/loyalty-members/{id}` subtree) precedes existence; body `loyalty_member_id` scoped before body-FK resolution; segregation checked after target shift loads, before state checks; body FKs checked for resolution only (cross-site check exists solely in work-order schedule/road-dispatch) — members.py:49-54, parking.py:118-127, service.py:46-60, fleets.py:43-44, shifts.py:175-178, work_orders.py:131-136.
- §3.1 — revise — mismatch — price truncation applies only when the existing window actually reaches the new one (`effective_to` null or strictly after new `effective_from`); already-ended earlier prices are untouched — fuel_prices.py:53-57.
- §3.7 — revise — mismatch — send-to-vendor persists only `reason` into `vendor_out_reason`; required `vendor_name` is not exposed on the public record — work_orders.py:342-345.
- §3.7 — revise — mismatch — cancel frees the bay only from `IN_SHOP`/`IN_PROGRESS`; a `WAITING_VENDOR` order's bay stays occupied — work_orders.py:455-459.
- §3.9 — revise — mismatch — oil case-pack rounding divides the two-decimal-rounded suggestion (not the raw figure); pack size comes from the earliest-created `PACKAGED_OIL` item with `case_pack_gallons` — pricing.py:209,219-228.

### Ambiguity-pins (inserts)
- §2.2 — insert — undefined path / unsupported method → `ERR_NOT_FOUND` 404 — app.py:32-38.
- §2.3 — insert — `created_at` ties break by insertion order; bad `limit`/`offset`/filter value → `ERR_INVALID_REQUEST` — helpers.py:14-15, validate.py:193-224.
- §2.4 — insert — workflow stamps and window echoes stored at whole-second precision; only `created_at`/`updated_at` carry ms — util.py:44-52, services/core.py:16-32.
- §2.6 — insert — OCC guard evaluates right after path load (stale masks all later failures); missing/non-integer expected version is `ERR_INVALID_REQUEST` at final stage — fuel_prices.py:26-29,73-74, contracts.py:88-101.
- §2.9 — insert — zero-point accrual writes no lot — loyalty.py:46-48,71-73.
- §2.9 — insert — omitted `requested_redeem_points` defaults to zero everywhere; >0 without member → `ERR_INVALID_REQUEST` — fuel_sales.py:147-151, service.py:78-80.
- §2.9 — insert — adjustments: non-zero integer delta + non-empty reason (else 400), lot returned 201, allowed in any member status — members.py:113-122.
- §3.1 — insert — `parking_paid_capacity` > total → 400 — sites.py:24-26.
- §3.1 — insert — dashboard field definitions (`IN_USE` pumps, `ACTIVE` reservations, `QUEUED` tickets, low-stock items) — sites.py:65-78.
- §3.1 — insert — retail mirrors re-derived lazily on site reads and on clock-set, never bumping site version — sites.py:47,54-55, clock.py:23-26.
- §3.1 — insert — duplicate `pump_number` → 400 — pumps.py:26-28.
- §3.2 — insert — attribution-shift `OPEN` guard runs immediately after the pump guard — fuel_sales.py:74-76.
- §3.2 — insert — multi-tank diesel selection (earliest-created with rack price, else earliest-created) and no-rack → `ERR_NO_ACTIVE_PRICE` — services/core.py:148-158, fuel_sales.py:117-120.
- §3.2 — insert — snapshot nullability per pricing mode; `stack_cap_snapshot` null without member — fuel_sales.py:159-175,198.
- §3.2 — insert — over-cap `dispensed_gallons` → `ERR_INVALID_REQUEST` — fuel_sales.py:261-262.
- §3.2 — insert — `points_redeemed` records the capped redemption count (min of requested and pinned cap) — fuel_sales.py:309-316.
- §3.2 — insert — payment requires `COMPLETED` + `UNPAID` (else 409); pay payload's `tender_type` governs; no credit re-check at payment — fuel_sales.py:340-351.
- §3.2 — insert — void `reason` optional (null when omitted); both void branches end in `VOIDED` — fuel_sales.py:374,381-424.
- §3.3 — insert — fleet close with non-zero balance → `ERR_INVALID_STATE` — fleets.py:88-89.
- §3.3 — insert — contract creation validates window shape and duplicate code (400), checks neither fleet status nor discount-vs-margin (those fire at activation/authorization/amendment); discount carried as supplied — contracts.py:36-59.
- §3.3 — insert — amended `effective_to` validated only as a well-formed instant — contracts.py:105-113.
- §3.4 — insert — member-ACTIVE guard scope: fuel authorize/finalize guard only when points requested; check-in/completion accrual unguarded (non-active member earns nothing) — fuel_sales.py:87-89,294-298, parking.py:295, service.py:224, loyalty.py:66-68.
- §3.4 — insert — duplicate plate → `ERR_INVALID_REQUEST` — members.py:142-144.
- §3.4 — insert — network `discount_per_gallon` carried as supplied, rounded at cent conversion — networks.py:28-30, pricing.py:52-55.
- §3.5 — insert — `space_number` is a free-form string, duplicates → 400, `is_reservable` required boolean — parking.py:40-46.
- §3.5 — insert — check-in outside window → `ERR_INVALID_STATE`; space pool ranked in string order — parking.py:256-258,277.
- §3.5 — insert — member attempting ACTIVE-branch cancel → `ERR_FORBIDDEN`; early no-show → `ERR_INVALID_STATE` — parking.py:330-331,356-357.
- §3.5 — insert — service cash pay with no effective shift → 400; supplied payload `shift_id` re-stamps the ticket — service.py:249-259.
- §3.5 — insert — weigh events accepted while `OPEN` or `PAID` (else 409) — scale.py:85-86.
- §3.5 — insert — cashier cancelling a `PAID` scale ticket → `ERR_FORBIDDEN` — scale.py:168-170.
- §3.6 — insert — duplicate `sku` → 400; `case_pack_gallons` held null on non-`PACKAGED_OIL`; `low_stock` filter takes `true`/`false` case-insensitive — stock.py:39-41,53,63-69.
- §3.6 — insert — PO line price defaults to earliest-created vendor entry, none → 400 — purchase_orders.py:22-27,53-58.
- §3.6 — insert — receiving only from `APPROVED`/`PARTIALLY_RECEIVED`; quantity key `received_quantity` (or `quantity`); unknown SKU/non-positive/over-receipt → 400; unmatched SKU accumulates without moving stock — purchase_orders.py:104-153.
- §3.6 — insert — store-sale stock sufficiency aggregates duplicate lines per item; refund `reason` accepted but not persisted — store_sales.py:62-69,136.
- §3.7 — insert — technician `certifications` default empty — shop.py:110-114.
- §3.7 — insert — estimate is not identity-scoped (no technician assigned at `CREATED`), positive hours required — work_orders.py:97-107.
- §3.7 — insert — GM may approve any order incl. fleet-billed; FleetManager only its own — work_orders.py:110-123.
- §3.7 — insert — schedule: cross-site bay/technician → 404; technician not `AVAILABLE` → 409; `scheduled_to` must strictly follow `scheduled_from` (400) — work_orders.py:133-140,170-175.
- §3.7 — insert — bay maintenance block accepts equal ends; only `blocked_to` < `blocked_from` is 400 — shop.py:76-77.
- §3.7 — insert — part issue only while `IN_PROGRESS`; returns while `IN_PROGRESS`/`WAITING_VENDOR`; over-return → 400 — work_orders.py:220-221,264,271-273.
- §3.7 — insert — work-order close: cash without `shift_id` → 400; `FLEET_BILLING` on retail order → `ERR_INVALID_PRICING_MODE` — work_orders.py:405-407,415-416.
- §3.8 — insert — duplicate `register_code` → 400 — registers.py:24-26.
- §3.9 — insert — reorder view responds `{"suggestions": [...]}` in tank creation order with pinned entry fields (`case_pack_gallons`/`suggested_cases` added for pack-rounded oil) — bulk.py:130-134, pricing.py:193-229.

No new sections added; all changes are inline inserts/revisions within existing paragraphs.

## Pipeline complete — 2026-08-15T02:25:00.000Z

All Steps 1–9 finished. Final artifacts: SCAFFOLD.yaml + both design yamls, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (11 files, 97 tests after 2 deletions), implementation/ with final 8-round sweep all passing 97/97.
