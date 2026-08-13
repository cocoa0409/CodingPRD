# Worklog — task_1483_wholesale_bakery_plant_dsd_bread

## Step 1: Create Task Directory — 2026-08-13T12:10:00.000Z

RESUME RUN: task directory `tasks/task_1483_wholesale_bakery_plant_dsd_bread/` already exists with an empty `workspace/` subdirectory (created by a prior terminated run at 2026-08-13 12:10). No worklog.md, no scaffold artifacts, no PRD, no tests, no implementation present. Step 1 treated as DONE per resume instructions; pipeline resumes from Step 2.

## Step 2: Generate Scaffold — 2026-08-13T14:28:37.000Z

All checks pass. The scaffold is complete and clean.

## Summary

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 15 (Plant, Product, Store, Driver, Line, StoreOrder, ProductionPlan, Batch, SanitationCycle, Route, RouteStop, StaleReturn, ThriftSale, IngredientIndex, SurchargeSchedule)
- State machines: 12 (incl. cyclic StoreOrder amendment loop, StaleReturn dispute negotiation cycle, SanitationCycle fail-retry loop, Batch with system OVERPROOFED auto-transition and RELEASED→REJECTED recall cascade)
- Calculations: 10 (incl. dual-variant stale_credit and surcharge_passthrough; tier-chained production_requirement with pinned evaluation order; per-line-round-then-sum credit rounding; nested min/max stocking; settlement shrink; thrift pool conservation)
- Validation rules: 10 priority tiers (auth → role/ownership → existence → shape → OCC → state → safety → temporal → referential → fiscal)
- Endpoints: 85 (incl. `/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Error codes: 28 (all referenced outside the catalog)
- Roles: 9 (8 functional + Any; entity-backed Driver and StoreReceiver; segregation-of-duties on bake/release, sanitation start/verify, return record/verify)
- Concurrency rules: 3 OCC rules (order amendment, plan create-supersede, batch scheduling), all 412 with `${var}`-bound versions
- §1.8 difficulty instances: 21 (R1×2, R2×3 covering modes a/b/c, R3×3 on different entities, R4×2 depths 3 and 2, R5×2 state-vs-fiscal and safety-vs-temporal, R6×2 cutoff-equality and stale-age-tier, R7×3 different entity pairs, R8×2 half-open vs buffered interval semantics, R9×2 credit-cents and thrift-units conservation)
- §1.9 corner instances: 45 entries (42 active + 3 `excluded_because` stubs), spanning entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model

**Verification:** all numeric asserts were pre-computed by executing the formulas (e.g., stale credit 448/398, surcharge 7→19 with clamp case 37, production plan 999→1099 vs 1000→1070 tier non-monotonicity, shrink liability 150/2700). A replay audit caught and fixed a systemic stale-OCC bug (plan `version` capture moved from create to lock response) and a broken stop-creation chain. `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-13T14:29:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1483_wholesale_bakery_plant_dsd_bread/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T14:50:55.000Z

Generation complete. All three Hard Contracts verified PASS mechanically.

## Output

- **File:** `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/workspace/PRD.md`
- **Line count:** 343

## Section list

1. Introduction (2 paragraphs — business-clock framing + segregation-of-duties/ledger pillars)
2. Global Specifications: §2.1 RBAC (headers, 8 roles + `Any`, entity-backed identity prose for `Driver`/`StoreReceiver`, opaque for the rest) · §2.2 Response Structure (byte-identical verbatim block, confirmed programmatically) · §2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields) · §2.4 Logical Clock & Ops-Run Day (startup `2026-08-01T00:00:00Z`, close_day sweeps) · §2.5 Common Resource Properties · §2.6 Cascading State Changes · §2.7 OCC · §2.8 Money/Units/Rounding · §2.9 Validation Order (10 priorities, explicit ordering) · §2.10 Segregation of Duties
3. Business Logic (9 subsections): §3.1 Master Data · §3.2 Store Order Lifecycle · §3.3 Production Planning · §3.4 Batch Scheduling & Line Execution · §3.5 Allergen/Sanitation · §3.6 Routes & Delivery · §3.7 Settlement & Shrink · §3.8 Stale Returns/Credit/Thrift · §3.9 Indices & Surcharge
4. Endpoint Definitions — 85 rows (matches scaffold 85), 4 columns only
5. Error Code Catalogue — 28 rows (matches scaffold 28), 2 columns only

## Hard Contract reports

- **Contract 1 (Field-Name Coverage):** 92/92 entity fields, 56/56 request-body inputs, 16/16 query params present verbatim in backticks — PASS (two passes run; first run's apparent misses were a regex artifact of the §2.2 JSON fences, re-run with fences stripped confirmed full coverage)
- **Contract 2 (Rule Coverage):** see audit below — PASS
- **Contract 3 (§3 Path Purity):** 526 backtick tokens scanned in §3, 0 paths / 0 bare methods / 0 method+path combos — PASS

## Zero-Silence Rule coverage audit (scaffold rule → PRD landing)

| Scaffold rule | PRD location |
|---|---|
| 3 OCC rules (`expected_store_order_version` / `expected_plant_version` / `expected_production_plan_version`, all `ERR_STALE_VERSION` 412) | §2.7 bullets; restated at point of use in §3.2, §3.3, §3.4 |
| 10 validation priorities, explicit ordering | §2.9 numbered list 1–10 with error IDs + statuses |
| Store suspend/reinstate + close_day auto-suspend (strictly > 0.15) | §3.1, §2.4 |
| Order cutoff (08:00:00Z instant, lead-time subtraction, equality allowed) | §3.2 |
| Order amendment accept vs reject branches (equal density) | §3.2 |
| Manual lock (before cutoff) vs system lock at close_day | §3.2 + §2.4 |
| Plan requirement computation, pinned order (gross-keyed tiers 10%/7%/5% at 1,000/5,000, ceil planned, ceil batches, flour 60% fraction → kg 1dp half-up) | §3.3 |
| Plan supersede + `ERR_DUPLICATE_PLAN_DATE` + plant version bump | §3.3 |
| Plan unlock/release/reconcile preconditions (`ERR_PLAN_NOT_RELEASABLE`, `ERR_SANITATION_REQUIRED`, `ERR_INVALID_STATE`) | §3.3 |
| Batch schedule guards (plan LOCKED/RELEASED, qty 1..capacity, half-open overlap, `ERR_LINE_NOT_AVAILABLE`, `ERR_ALLERGEN_SEGREGATION_VIOLATION`) | §3.4 |
| Proof window 60–120 min inclusive; close_day auto-OVERPROOFED >120 | §3.4, §2.4 |
| Complete-bake side effects (`bake_completed_at`, `completed_by_user_id`, `fresh_until`, line residue/DIRTY) | §3.4 |
| Reject cascade, all 6 from-states incl. RELEASED recall, 3 hops (plan shortfall → stop `shortfall_flag` → order SHORTED) | §3.4 |
| Sanitation matrix 0/30/120/90; cycle REQUESTED→IN_PROGRESS→VERIFIED/FAILED→retry loop; dwell + SoD | §3.5 |
| Route rest buffer 30 min; stop-create gates (order state, `planned_units == total_units`, RELEASED batches covering all lines) | §3.6 |
| Loading freeze, dispatch capacity, deliver freshness (min `fresh_until` minus store floor, equality), stocking allocation, refused-at-zero-credit | §3.6 |
| Reconcile cascade → FULFILLED / PARTIALLY_FULFILLED | §3.6 |
| Settlement math (shrink = loaded − delivered, ratio vs 0.10 hard limit with `override_shrink_limit`, 2% tolerance with ceil allowance, 150¢/unit liability, returned-stale informational exclusion) | §3.7 |
| Stale credit dual variant (24h/48h tiers 1.00/0.50/0.00, LIMITED cap 0.50, per-line half-up then sum, verified variant pins original creation clock); 72h window; 50,000¢ cap; dispute round; credit/reverse balance postings | §3.8 |
| Thrift pool inflow/outflow, floor = half base price rounded up, void conservation | §3.8 |
| Surcharge formula (per-ingredient delta vs baseline, share-weighted, clamp 0–0.15, half-up cents), forecast→publish 2-hop cascade | §3.9 |
| Field defaults/initials (`day_index` 0, `stale_credit_tier` STANDARD, 600-min drive cap, zeroed accumulators/counters, null-until timestamps) | §2.4, §3.1, §3.2, §3.3, §3.6, §3.8, §3.9 |

No content was drawn from `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`; neither file was opened.

## Step 5: Generate Unit Tests — 2026-08-13T15:40:00.000Z

Pytest collects all 84 tests cleanly.

## Summary

**Generated artifacts** under `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/`:

### Stage 1 — `test_helpers/` (10 files)
- `types.py` — Entity TypedDicts (14 entities) + status enums + role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~64 endpoints)
- `api_errors.py` — 27 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — `assert_<entity>()` for all 14 entities
- `factories.py` — Payload factories (input fields only)
- `constants.py` — All numeric thresholds from §3 calculations
- `test_users.py` — Shared role headers + per-instance builders for entity-backed roles (`Driver`, `StoreReceiver`)
- `fixtures.py` — Tier 0 creators, Tier 1 state walkers (`walk_batch_to_released`, `walk_route_to_dispatched`), Tier 2 `setup_plant_with_master_data`, Tier 3 chain fixtures (`setup_released_batch_scenario`, `setup_dispatched_route_scenario`, `setup_delivered_stop_scenario`, `setup_verified_stale_return_scenario`), Tier 4 `setup_locked_plan_with_gross`, Tier 5 `setup_settled_route_scenario`, plus `setup_line_dirty_with_sesame`, `setup_two_product_delivered_scenario`, `setup_surcharge_scenario`
- `__init__.py` — Barrel re-export

### Stage 2 — `test_suite/` (20 files: 1 conftest + 19 test files)
- `conftest.py` — Session-scoped `api` fixture + role header fixtures
- 84 test functions across 19 files, each carrying one verbatim `Design:` line

### Coverage
- **Queue A (Difficulty)**: 21 instances × 2 tests = **42 tests**, all translated
- **Queue B (Corner)**: 42 non-stub instances × 1 test = **42 tests**, all translated
- **Stubs correctly not translated**: `sanitation_retry_loop_covered`, `batch_reject_cascade_covered`, `dual_variant_calculations_covered` (all owned by Queue A instances)
- **Skipped**: 0

### Stage 1 / Stage 2 self-checks
- **Stage 1**: `test_helpers` imports cleanly; `ApiClient` exposes 91 public methods; 9 setup_* fixtures exported; `TEST_USERS` has all role constants
- **Stage 2 citation pass**: All 84 tests carry a `Design: <queue>/<rule>/<instance.name>` tag (C4); all docstrings carry a `PRD §x.y` citation with a verbatim substring that greps into `workspace/PRD.md` (C1/C2/C3); no `pytest.mark.skip` / `skipif` / `xfail`; no `scaffold`/`Table N` leakage in generated comments
- **Per-instance audit**: script-verified every Queue A instance has ≥2 tests and every non-stub Queue B instance has ≥1 test; 0 missing, 0 short, 0 extra tags
- **Pytest collection**: `pytest --collect-only` succeeds, 84 tests collected

Key file paths:
- `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/test_suite/`

## Step 6: Generate Implementation — 2026-08-13T15:20:00.000Z

All 85 endpoints (1 clock + 84 bakery endpoints from the PRD table) are implemented.

## Summary

### Files created in `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/workspace/implementation/`

- `start.sh` — foreground launcher; guarded `pip install` (no-op when Flask importable); `exec python3 app.py`; reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, error handlers (ApiError → envelope; 404/405 → ERR_NOT_FOUND envelope)
- `db.py` — in-memory store (dicts keyed by id); logical clock initialized exactly to `2026-08-01T00:00:00Z`, never falls back to wall-clock
- `errors.py` — `ApiError` + all 28 error ID constants from the scaffold
- `response.py` — `{meta, response_type, data}` envelope; `meta` contains `api_request_id` (`req_…`), `api_request_timestamp` (ISO 8601 with 3 fractional digits), plus `limit`/`offset`/`total_count`/`has_more` on lists
- `middleware.py` — `X-User-ID` / `X-User-Role` validation against the 8 declared roles; role-authorization helper
- `helpers.py` — entity minting (`id`, `created_at`, `updated_at`, `version`), body/field validation, ISO datetime/date/period parsing, pagination (limit default 10, min 1, max 100, offset default 0), `created_at`-ascending list sorting
- `routes/` — one module per resource (clock, plants, products, stores, drivers, lines, store_orders, production_plans, batches, sanitation_cycles, routes, route_stops, stale_returns, thrift_sales, ingredient_indices, surcharge_schedules)
- `services/calculations.py` — production requirement (tiered buffer keyed on gross, ceil, flour round-half-up 1dp), sanitation changeover matrix, stale credit (per-line round-half-up then sum, age floor-hours, LIMITED tier cap 0.50), surcharge pass-through (delta vs baselines, clamp [0, 0.15], round-half-up), route settlement shrink (tolerance 2% ceil allowance, hard limit 10%, 150 cents/unit), thrift stock pool (inflow from VERIFIED+DISPUTED+CREDITED+REVERSED lines with positive rate, outflow from RECORDED sales), stale ratio (exact rational)
- `services/cascades.py` — batch-reject 3-hop cascade (plan shortfall → stop shortfall_flag → order LOCKED→SHORTED), stop reconcile cascade (FULFILLED/PARTIALLY_FULFILLED), index-publish cascade (PROVISIONAL→FINALIZED when both FLOUR+BUTTER published; product surcharge sync), plan supersede cascade, close-day sweeps (overproof > 120 min, suspend stores with stale_ratio strictly > 0.15, lock CONFIRMED orders past cutoff)
- `services/clock.py` — get/set logical clock

### Endpoint count: 85

1 clock + 84 bakery endpoints, matching PRD §4 exactly.

### PRD ambiguities resolved

1. **Cancel with no body vs `reason` field** — PRD lists `reason` as input on suspend/skip/reject/reject-return/unlock. Treated `reason` as optional free-text: accepted if present, not required, not stored (PRD does not declare a persisted field for it).
2. **`stale_ratio` field on Store** — Stored at creation as `0`, recomputed and embedded on every GET/list response (avoids stale values without requiring a touch on every counter update); PRD describes it as purely derived.
3. **Route `shrink_units` / `shrink_liability_cents` before settle** — PRD says "carry no value until settlement"; initialized to `null` on creation and populated only at settle.
4. **RouteStop `delivered_units` / `on_shelf_units_observed` / `stocked_units` / `refused_units` before deliver** — initialized to `null`; populated at deliver.
5. **Sanitation-cycle creation when another cycle is already REQUESTED/IN_PROGRESS on the same line** — PRD only blocks plan release and batch scheduling; creation of an additional REQUESTED cycle is allowed (no prohibition in PRD).
6. **Batch creation against DIRTY line with same allergen class** — PRD §3.4 says rejection applies only when classes differ; same-class scheduling on DIRTY line is allowed.
7. **Driver window-overlap check scope** — Only routes in non-terminal states (`PLANNED`, `LOADING`, `DISPATCHED`, `COMPLETED`) participate; `SETTLED`/`CANCELLED` routes don't block.
8. **`expected_*_version` must be supplied** — PRD §2.7 says the three guarded endpoints "require" the field; missing field → `ERR_INVALID_REQUEST`, non-integer → `ERR_INVALID_REQUEST`, mismatched integer → `ERR_STALE_VERSION` (412).
9. **Stale-return creation ownership** — Any user with role `Driver` may record; `recorded_by_driver_id` captures `X-User-ID` for the segregation-of-duties check at verify. (PRD does not require the recording driver to be the route's driver.)
10. **`has_more` semantics** — `(offset + len(page)) < total_count`.
11. **Plan creation duplicate guard** — PRD §3.3: "any state other than DRAFT" blocks; SUPERSEDED plans are excluded from the blocker set (they are terminal and the natural outcome of the supersede cascade).
12. **Thrift pool inflow restricted to lines with positive rate** — Implemented as specified: age must be ≤ 48 h (rate > 0) at the original pickup clock.

## Step 7: Run Tests and Iterate — 2026-08-13T16:10:00.000Z

All 8 rounds pass 84/84. Clean sweep achieved.

## Summary

- **Iterations run**: 2 (iteration 1: 11 unique failing tests across the 8-round union; iteration 2: 0 failures, 84/84 in all 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/test_helpers/fixtures.py` — `setup_locked_plan_with_gross`: plan was created with default `bake_date=2026-08-09` while the order's `delivery_date` is 2026-08-10; PRD §3.3 sums only LOCKED orders whose `delivery_date` equals the plan's `bake_date`, so the computed requirement was always 0. Fixture now passes `bake_date="2026-08-10"`. (Fixed `TestProductionRequirementChainedTierOrder` ×2 and `TestBufferTierBoundary`.)

- **Fixes applied to `test_suite/`** (test bugs, not implementation bugs):
  - `test_16_compensating_invariants.py` — module-level helper `_verified_thrift_pool_ctx` referenced the `api` fixture name (undefined at module scope → `NameError`); switched to `api_client` imported from `test_helpers`.
  - `test_14_cross_entity_dependencies.py` — `_confirmed_order_with_released_batch` confirmed the second order after the clock had been advanced past the order cutoff (ERR_ORDER_CUTOFF_PASSED in setup); moved create+confirm of `o2` to before the clock advance, consistent with PRD §3.2 cutoff semantics.
  - `test_10_route_settlement.py` — `test_route_capacity_exact_boundary` created route 2 with window 10:30–12:00, which overlaps route 1's 08:00–12:00 window, so the PRD §3.6 rest-buffer check correctly rejected setup; moved route 2's window to 12:30–14:00 (exactly the accepted 30-minute boundary).

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/routes/batches.py` — `create_batch`: reordered checks to match PRD §2.9 — allergen segregation (step 7, safety) now fires before line-schedule overlap (step 8, temporal), which fires before `ERR_LINE_NOT_AVAILABLE` (step 9) and the batch-capacity cap (step 10). (Fixed `TestAllergenViolationBeatsScheduleOverlap::test_allergen_violation_wins_when_both_apply`.)
  - `workspace/implementation/routes/store_orders.py` — `request_amendment`: moved the OCC `expected_store_order_version` check (§2.9 step 5) ahead of the CONFIRMED-state check (step 6), so a stale version on an `AMENDMENT_PENDING` order yields `ERR_STALE_VERSION` (412) as §2.7 requires. (Fixed `TestOccAmendment::test_occ_amendment_returns_412_on_stale_version`.)

- **Flakiness note**: `TestStaleAgeTierBoundary::test_age_25h_drops_to_half_rate` failed once in iteration 1 round 4 with `ConnectionResetError` (infra-level connection reset under 8× parallel load, not an assertion failure); it passed in all 8 rounds of iteration 2.

## Step 8: Finalize PRD — 2026-08-13T16:25:00.000Z

The task is complete. PRD_FINALIZED.md has been produced with exactly one minimal in-place revision.

## Summary

**Line counts / %-delta**: PRD.md = 343 lines; PRD_FINALIZED.md = 343 lines (0% delta; one line revised in place, no lines added or removed).

### Changes made

- **§3.6 (Route Composition)** — **revise** — appended a boundary pin to the rest-buffer sentence: "the buffer is strict — a separation of exactly 30 minutes between the windows is allowed, and only separations of less than 30 minutes (including overlapping windows) are rejected." The PRD's "falls within 30 minutes" was the only temporal boundary in the document left unpinned (cf. §3.2 cutoff "equality is allowed", §3.4 proof window "both bounds inclusive", §3.6 freshness "equality is allowed"); the fixed `test_10_route_settlement.py::test_route_capacity_exact_boundary` setup (window moved to 12:30–14:00, exactly 30 minutes after route 1's 12:00 end) is load-bearing on exactly-30 acceptance — `implementation/routes/routes.py:59` (`if start_dt < o_end + buffer and end_dt > o_start - buffer`, strict both directions).

### Step-7 items that required no PRD edit (with evidence)

- **`test_helpers/fixtures.py` bake_date** — pure fixture bug; PRD §3.3 already pins "every `LOCKED` store order … whose `delivery_date` equals the plan's `bake_date`" verbatim; impl `implementation/services/calculations.py:49-55` matches exactly.
- **`test_16` NameError** — mechanical test-infra bug, no behavioral content.
- **`test_14` clock-advance fix** — pure test bug; PRD §3.2 already pins confirm-time cutoff ("the clock must be at or before the cutoff (else `ERR_ORDER_CUTOFF_PASSED`)"); impl `store_orders.py:113-114` matches.
- **`batches.py` check reorder** — impl was fixed to *conform to* PRD §2.9, which already explicitly orders step 7 (allergen segregation) < step 8 (line schedule overlap) < step 9 (`ERR_LINE_NOT_AVAILABLE`) < step 10 (batch-capacity cap); current impl `implementation/routes/batches.py:64-90` matches §2.9 step-for-step. PRD already uniquely determines the behavior.
- **`store_orders.py` OCC reorder** — impl was fixed to conform to PRD §2.9 (step 5 OCC before step 6 state preconditions) and §2.7 (412 on stale version); current impl `store_orders.py:139-142` matches, and the other two OCC endpoints (`production_plans.py:31-39`, `batches.py:50-58`) follow the same shape→OCC→state order, so §2.9's ordering is globally consistent as written.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 (§3.6 rest-buffer boundary)**:
- (a) Subject: driver rest-buffer (`ERR_DRIVER_WINDOW_OVERLAP`) boundary semantics at route creation.
- (b) Paths enumerated: repo-wide greps for `REST_BUFFER|ERR_DRIVER_WINDOW_OVERLAP|window_start_at|window_end_at`, `buffer|rest`, and bare `30` across `implementation/`. The sole enforcement site is `create_route` in `implementation/routes/routes.py:50-60` — strict `<`/`>` comparisons, symmetric in both directions, same-driver only, considering routes in `PLANNED/LOADING/DISPATCHED/COMPLETED`. `implementation/routes/drivers.py` contains no window logic (CRUD only); `implementation/services/calculations.py:104`'s `30` is the sanitation changeover matrix (unrelated subject). Section 4 defines no route-update endpoint, so windows are immutable post-creation. Test evidence cross-checked: `test_11_line_driver_overlap.py::test_window_at_exactly_30_minutes_accepted` (exactly-30 accepted), `test_window_within_30_minutes_rejected` (20-minute gap rejected), and the fixed test_10 setup.
- (c) Wording adjustment: original sentence kept verbatim; the appended clause is direction-neutral ("separation of exactly 30 minutes between the windows") to match the impl's symmetric check, and explicitly covers overlapping windows on the rejection side. I deliberately did **not** pin which route statuses count as "already has a route" (the impl filters to active states, but no Step 7 item touches that — out of hard scope — and preserving the original wording introduces no new claim).

Result: `/home/ubuntu/github/CodingPRD/tasks/task_1483_wholesale_bakery_plant_dsd_bread/workspace/PRD_FINALIZED.md` differs from `PRD.md` by exactly one sentence-scoped revision; every other Step-7 item traced to behavior the PRD already uniquely determines.

## Step 9: Complete PRD — 2026-08-13T16:35:00.000Z

Done. All 23 edits applied in-paragraph; no sections added or removed.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (343 lines, 52,584 chars) → `workspace/PRD_COMPLETED.md` (343 lines, 53,791 chars). Char delta: **+1,207**. Line count unchanged (all changes are inline inserts/revisions).

**Counts:** 15 ambiguity-pins, 8 mismatch-revisions (23 total changes).

### Ambiguity-pins (PRD silent, inserted impl behavior)

- §2.3 Pagination — insert — ambiguity — pinned clamping of out-of-range `limit`/`offset` (limit<1→1, >100→100, offset<0→0), non-integer fallback to defaults, and `id`-ascending tie-break after `created_at` — impl `helpers.py:166-195`
- §2.5 Common properties — insert — ambiguity — `version` starts at 1 at creation — impl `helpers.py:18`
- §3.1 Plant — insert — ambiguity — `baseline_flour_index`/`baseline_butter_index` must be numbers > 0 — impl `routes/plants.py:22-23` (`req_number` default rejects ≤ 0)
- §3.1 Product — insert — ambiguity — `unit_weight_g`, `shelf_life_hours`, `base_price_cents`, `batch_capacity_units` are positive integers (not just "> 0") — impl `routes/products.py:29-38`
- §3.1 Store — insert — ambiguity — `lead_time_hours`/`shelf_capacity_units` positive integers, `min_remaining_life_hours_on_delivery` integer ≥ 0 — impl `routes/stores.py:34-38`
- §3.1 Driver — insert — ambiguity — `max_daily_drive_minutes` must be a positive integer when supplied — impl `routes/drivers.py:24-28`
- §3.2 Order placement — insert — ambiguity — `lines` must be a non-empty array; `qty` is a positive integer — impl `routes/store_orders.py:22-38`
- §3.4 Batch overlap — insert — ambiguity — overlap check covers batches in `SCHEDULED`, `MIXING`, `PROOFING`, `BAKING`, `COOLING`, or `OVERPROOFED` (pins "scheduled or in-flight") — impl `routes/batches.py:25,74-82`
- §3.6 Rest buffer — insert — ambiguity — only routes in `PLANNED`/`LOADING`/`DISPATCHED`/`COMPLETED` block; `SETTLED`/`CANCELLED` do not — impl `routes/routes.py:24,52-56`
- §3.6 Deliver — insert — ambiguity — `delivered_units` and `on_shelf_units_observed` are integers that may be zero — impl `routes/route_stops.py:113-114`
- §3.8 Stale return — insert — ambiguity — return exposes `created_at_logical` (creation logical clock), the basis for verified-variant age recomputation — impl `routes/stale_returns.py:96,147,193`
- §3.8 Stale return — insert — ambiguity — a line whose batch has no `bake_completed_at` skips the 72h window check and contributes zero credit — impl `routes/stale_returns.py:56-57`, `services/calculations.py:167-169`
- §3.9 Index — insert — ambiguity — duplicate (plant, ingredient, period) rejected with `ERR_INVALID_REQUEST` (400) — impl `routes/ingredient_indices.py:29-35`
- §3.9 Schedule — insert — ambiguity — duplicate (product, period) rejected with `ERR_INVALID_REQUEST` (400) — impl `routes/surcharge_schedules.py:41-43`
- §3.9 Publish — insert — ambiguity — `published_value` must be greater than zero — impl `routes/ingredient_indices.py:73`

### Mismatch-revisions (PRD described behavior impl does not exhibit)

- §3.1 Store suspend — revise — mismatch — dropped "the request records a free-text `reason`" (impl never reads/stores it) — impl `routes/stores.py:76-85`
- §3.3 Plan unlock — revise — mismatch — dropped "records the planner's free-text `reason`" — impl `routes/production_plans.py:102-118`
- §3.3 Duplicate plan guard — revise — mismatch — guard reads "any state other than `DRAFT` or `SUPERSEDED`" (literal PRD would let a SUPERSEDED plan block creation; impl exempts it) — impl `routes/production_plans.py:42-49`
- §3.4 Complete-bake line rewrite — revise — mismatch — line's `version` increments on every bake completion, not only when cleanliness flips to `DIRTY` — impl `routes/batches.py:198-202` (`touch(line)` unconditional)
- §3.4 Batch reject — revise — mismatch — dropped "the request carries a free-text `reason`" — impl `routes/batches.py:220-230` (no body parsed)
- §3.6 Skip stop — revise — mismatch — dropped "records a free-text `reason`" and the "requires only that the route is DISPATCHED" phrasing (impl also requires driver ownership and stop `PENDING`) — impl `routes/route_stops.py:162-178`
- §3.8 Return verify/resolve — revise — mismatch — pinned impl's endpoint-specific order: state (and SoD for verify) checked before body validation, deviating from §2.9's global shape-before-state order; also pinned that dispute resolution does not re-apply segregation of duties — impl `routes/stale_returns.py:133-139,177-187`
- §3.8 Return reject — revise — mismatch — dropped "the request carries a `reason`" — impl `routes/stale_returns.py:245-254`

Everything else in the impl (cutoff math, proof window bounds, sanitation matrix, credit rate table/rounding, thrift pool, surcharge formula/clamp, settlement shrink/liability math, all cascade hops, OCC guards, role table, error catalogue) was already uniquely pinned by the PRD and left untouched.
