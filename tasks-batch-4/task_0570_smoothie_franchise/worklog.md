# Worklog — task_0570_smoothie_franchise

## Step 1: Create Task Directory — 2026-07-09T04:52:59.000Z

Directory `tasks/task_0570_smoothie_franchise` was pre-allocated by the user (index scan skipped per instruction). Created `workspace/` subdirectory inside it.

## Step 2: Generate Scaffold — 2026-07-09T05:27:13.000Z

All three artifacts are complete and pass `scaffold_lint.py` cleanly. Final verification confirms the structure.

## Summary

Generated a fresh **Expert**-difficulty scaffold for **task_0570_smoothie_franchise** (Smoothie & Juice Bar Franchise), built purely from the scenario + skill spec. All three files written and lint-clean (`VERDICT: clean lint`, 297 calls scanned).

**Complexity profile:** primary `ledger_reconciliation` + secondary `quota_allocation`; layers dual-variant / cascading side effects / OCC / derived-field reconciliation; hybrid topology; parallel state-machine shape; hierarchical_override roles; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **13 entities:** Franchisee, Store, DeliveryVehicle, Ingredient, InventoryLot, MenuItem, BoostAddIn, Customer, Subscription, Order (embedded lines), PointsTransaction (append-only ledger), CateringBooking, DailyReconciliation. 13 FKs, all with reverse-reachability GETs.
- **6 state machines:** Store (posture), Order (**parallel** payment × fulfillment), Subscription (**cyclic** ACTIVE↔PAST_DUE), InventoryLot (FIFO/spoilage), CateringBooking (branching), DailyReconciliation.
- **2 concurrency rules** (OCC): store-config stale-version, subscription plan-change stale-version — both 412.
- **10 calculations:** order_line_pricing (tiered/credit), order_total_assembly (pinned round-per-line-then-sum), order_cogs (**provisional vs final FIFO**), royalty_computation (**gross vs net + rebate boundary**), inventory_fifo_consumption, points_earned, loyalty_tier_derivation, reconciliation aggregation, catering_quote, order_nutrition.
- **18 validations** (priority-ordered), **49 endpoints**, **19 errors**, **5 roles** (PlatformAdmin/opaque, Franchisee, StoreStaff, Customer entity-backed, Anonymous).

Endpoint count (49) runs above the Expert 20–32 guideline — driven by FK reverse-reachability GETs + per-entity lifecycles across the scenario's 8 subsystems, not padding (the skill treats those bands as guidelines and permits going higher when the scenario genuinely needs the surface).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × 2 instances = **18 instances**, every formula-derived assert precomputed to a literal (COGS 420/570, royalty GROSS 60 vs NET 12, tiered line 142/total 153, per-line rounding 1424 vs 1425, tier crossing at 500→SILVER, spoilage 500, rebate 50000→2500/3500, inventory 150-unit boundary, points/inventory conservation).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **30 instances** across 8 taxonomy sections — 22 active corner tests (creation/defaults/not-found/required-fields/computed, invalid-transition/terminal/idempotency, catering_quote, 6 validation-error triggers, listing/pagination, RBAC unauthorized/ownership/unauthenticated, both OCC 412 races, immediate-consistency) + 8 `excluded_because` stubs pointing to the §1.8 instances that already cover them.

Files at `tasks/task_0570_smoothie_franchise/{SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml}`.

## Step 3: Copy Shared Files — 2026-07-09T05:27:13.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0570_smoothie_franchise/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-09T05:34:38.000Z

The PRD is complete and all three hard contracts pass. Here is the summary.

## PRD Generation Summary — task_0570_smoothie_franchise

**Output:** `workspace/PRD.md` (~306 lines)

**Domain:** Smoothie & juice-bar franchise — a ledger-reconciliation system with quota allocation (FIFO inventory), parallel order state machines, cyclic subscriptions, and OCC.

**Structure:**
- §1 Introduction — 3 paragraphs (business context + testability angle)
- §2 Global Specs — 9 domain-derived subsections: Access Control, Response Structure (verbatim), Pagination, Common Properties/Versioning, Monetary/Quantity Precision, Optimistic Concurrency Control, Logical Clock, Nested Retrieval/Existence, Request Evaluation Order
- §3 Business Logic — 8 lifecycle subsections: Franchisees/Stores/Vehicles, Catalog/Inventory/Spoilage, Customers/Points Ledger/Tiers, Subscriptions, Order Placing & Pricing, Paying/Fulfilling/Cancelling, Catering Bookings, Daily Reconciliation & Royalty
- §4 Endpoint table (4 columns, 50 endpoints)
- §5 Error catalogue (2 columns, 19 error IDs)

**Coverage audits:**

```
Field coverage check:
- entities[].fields + endpoints inputs/params: 105 required, 105 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: expressed as explicit ordered list in §2.9 — 0 missing
- concurrency_rules[] OCC: 2 checked (store-config + subscription change-plan), both name write op + expected_store_version/expected_subscription_version + ERR_STALE_VERSION/412 — 0 missing
- state_machines[].transitions: Store(5), Order(4), Subscription(6), InventoryLot(3), CateringBooking(3), DailyReconciliation(2) — all from/to + preconditions + side-effects expressed — 0 missing
- calculations[]: 10 checked (line pricing, total assembly, points_earned floor, loyalty tier, FIFO consumption, COGS provisional/final, royalty+rebate, reconciliation, catering quote, nutrition) — all reconstructible, no pseudocode/fuzzy words — 0 missing
- validations[] conditions: 18 matchable to error_id in prose — 0 missing
- endpoints[].side_effects / applies_to: cascades + multi-endpoint scopes (STORE_NOT_OPEN, INSUFFICIENT_INVENTORY, NO_ACTIVE_SUBSCRIPTION) enumerated — 0 missing
- entities[].fields[] structured content (defaults/initial values): reconstructible — 0 missing
- sibling-branch symmetry: renewal 4-branch + store transitions rendered at equal density — 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 420
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path tokens: 0
Status: PASS
```

**Key transcription decisions:** boundary inclusivity preserved verbatim (rebate `net_sales ≥ 50000` inclusive, inventory `required == available` succeeds, tier `≥ 500 → SILVER` / `≥ 1500 → GOLD`); pinned round-per-line-then-aggregate order stated; floor for points and ceil for units called out against the default round-half-up; parallel `fulfillment_status × payment_status` dimensions and their independent evolution described; `PointsTransaction` explicitly noted as lacking `updated_at`/`version` (common_fields:false). Constants embedded in prose with unit conversion ($1/$2 upcharges, $2/head service fee, $500 rebate threshold, 8% tax). Did not open either withheld SCAFFOLD_*_DESIGN.yaml file.

## Step 5: Generate Unit Tests — 2026-07-09T05:57:40.000Z

Test infrastructure for `task_0570_smoothie_franchise` is complete.

## Files written

**test_helpers/ (Stage 1)** — `__init__.py` (barrel), `types.py` (13 entity TypedDicts + 15 enums; `PointsTransaction` correctly omits `updated_at`/`version` per its `common_fields: false`), `api_client.py` (48 endpoint methods), `api_errors.py` (20 error IDs + HTTP status map registered with framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared constants for PlatformAdmin/Anonymous + per-instance `make_*_headers` builders for the three entity-backed roles, plus `NO_AUTH_HEADERS`), `fixtures.py` (granular builders + composites: `create_open_store`, `setup_order_env`, `setup_catering_env`, `advance_order_to_completed`, identity-threaded throughout).

**test_suite/ (Stage 2)** — `conftest.py` + 7 domain-named test files, **58 tests total**.

## Test counts per queue

- **Queue A (Difficulty):** 36 tests — all 18 instances covered by exactly 2 tests each.
- **Queue B (Corner):** 22 tests — all 22 non-stub instances covered by exactly 1 test each.

Every test carries exactly one verbatim `Design:` tag (58 tags / 58 functions); all tag instance names resolve to a real `name:` in the source YAMLs; all PRD citations were grep-verified verbatim against `PRD.md`.

## Instances skipped
- **The 8 `excluded_because` corner stubs** (`cogs_provisional_vs_final_covered`, `royalty_gross_vs_net_covered`, `allergen_conflict_covered`, `store_not_open_covered`, `insufficient_inventory_covered`, `catering_capacity_exceeded_covered`, `vehicle_double_booked_covered`, `vehicle_unavailable_covered`) were not translated — each cross-references a Difficulty instance that owns the assertion; all cross-refs verified to resolve. No placeholders emitted.

## Key adjudication note
For the difficulty instance `allergen_safety_beats_inventory_constraint`, PRD §2.9's fixed evaluation order does **not** pin the allergen business-safety rule ahead of the inventory business rule (both are "beyond the ordered gates"), so hard-coding that precedence fails unique-derivability. Per the skill's validation-priority silence pattern I tested the allergen rule in **isolation** (sufficient stock present, so only allergen can fail) via two distinct triggers (menu-item allergen and boost allergen), keeping both tests faithful to the instance's asserted `ERR_ALLERGEN_CONFLICT` outcome. By contrast `store_state_beats_points_fiscal` **is** PRD-pinned (store posture is gate 7, ahead of the beyond-gate points check), so it was translated as a genuine precedence test.

## Step 6: Generate Implementation — 2026-07-09T05:57:40.000Z

All 49 endpoints from the PRD endpoint table are implemented and the server boots cleanly with correct in-memory-only state (verified fresh clock default `2026-05-01T00:00:00Z`, empty store at boot). The implementation is complete.

## Summary

**Files written** (all under `workspace/implementation/`):
- `app.py` — single-file Flask app (~1500 lines): envelope, auth/RBAC, all 49 routes, state machines, calculations, validations
- `requirements.txt` — `Flask==3.0.3`
- `start.sh` — guarded-install foreground launcher (`exec python3 app.py`, `0.0.0.0:$PORT`, default 10000)

**Endpoint count:** 49, matching the PRD §4 table exactly.

**Verified behaviors** (live smoke tests): full order lifecycle (pricing → tax 8% → COGS provisional/final divergence 100 vs 140 → FIFO consumption → points earn floor → reconciliation net/gross/royalty+marketing → franchisee lifetime accrual), OCC 412 on stale store version, invalid transition 409, RBAC 403, not-found 404, insufficient-inventory 409, subscription credit application + cancel restoration, logical-clock advance + spoilage sweep with `mtd_spoilage_cents` accrual, and the ERR_INVALID_REQUEST(400) vs ERR_VALIDATION(422) split. In-memory dicts only; no seeding at startup.

**Key design points honored:** exact envelope (`meta`/`response_type`/`data`, `req_` ids, 3-digit-ms UTC timestamps from the logical clock), pagination `limit`/`offset`/`total_count`/`has_more`, `Decimal` + ROUND_HALF_UP for money (floor for points, ceil for ingredient units), version bump + `updated_at` on every mutation including cascaded children, and the §2.9 validation priority order.

**PRD ambiguities resolved by interpretation:**
1. **Timing of the REDEEM points transaction.** Neither the pay nor cancel side-effect lists mention REDEEM, yet the ledger model requires it (balance = sum of deltas; `lifetime_points_earned` explicitly *excludes* REDEEM). I create the REDEEM debit at **placement** (where the `ERR_INSUFFICIENT_POINTS` check lives, per validation priority 17 `applies_to: POST /orders`), making check+debit atomic, and I do **not** restore it on cancel — consistent with cancel reversing only *payment* effects and with there being no reason-code for un-redeeming.
2. **ERR_INVALID_REQUEST (400) vs ERR_VALIDATION (422).** Missing/typed/enum/negative/pagination-range failures → 400 (the priority-3 well-formedness list); stricter domain-range violations that are still non-negative (rate outside [0,0.5]/[0,0.2], `>= 1` minimums like `catering_capacity`/`headcount`/`qty`) → 422 ERR_VALIDATION.
3. **Zero-delta point events.** EARN and SUBSCRIPTION_BONUS transactions are written only when their delta > 0 (no zero-value ledger rows).
4. **Catering "active" set** for overlap/capacity excludes only CANCELLED (includes REQUESTED/CONFIRMED/COMPLETED), per the PRD's explicit "cancelled bookings are excluded" wording; half-open interval comparison with adjacency allowed.
5. **Booking-complete-before-prep-window** and **"window in the past"** timing failures map to ERR_INVALID_STATE (409) and ERR_INVALID_WINDOW (422, checked as `window_start < clock`) respectively.
6. **Store PATCH with `status` equal to current** is treated as a no-op (no self-transition error), so config-only patches that echo the current status still succeed; any *changed* status must be a defined transition.
7. **`created_at` FIFO tie-break:** since `created_at` derives from the logical clock (which can be static), I keep an internal monotonic `_seq` as the final deterministic tie-break after `(received_at, created_at)`, never `id`.

One environment note: a stale `app.py` server from a concurrent task was occupying a port during testing; I tested on an isolated port and cleaned up my process afterward.

## Step 7: Run Tests and Iterate — 2026-07-09T06:03:45.000Z

All 8 parallel rounds pass 58/58. Clean sweep achieved.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 verification). Fixed on the first fix batch.

**Root cause:** A single implementation over-restriction masqueraded as 9 independent failures across `test_01` (pagination) and `test_07` (all catering tests). The menu-item factory (`create_menu_item_payload`) and `setup_catering_env` create PRD-valid menu items with `recipe: []` (e.g. a `WELLNESS_PACK` party box that consumes no tracked inventory). The implementation rejected every such creation with `ERR_INVALID_REQUEST - recipe must be a non-empty list`, which:
- broke the pagination test (both menu items failed to create, so `list` returned 0 items), and
- broke all catering setups (the catering menu item couldn't be created).

**Tests deleted:** None. All 9 failing tests are PRD-faithful — the fixtures build preconditions consistent with PRD.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py`, menu-item creation handler (line ~975): removed the `len(recipe_raw) == 0` rejection, keeping only the list-type check. PRD §3.2 describes `recipe` as "the SMALL-size ingredient list" with no non-empty requirement, and §2.9's well-formedness gate only requires required fields to be *present* — an empty list is present. The non-empty constraint traced to no verbatim PRD sentence, so it was an implementation-only over-restriction rejecting valid requests.

Final state: 58/58 passing across all 8 concurrent rounds, no flakiness observed.

(Orchestrator verification: re-read all 8 `results.{1..8}.json` independently — every round reports `passed=58 / total=58`.)

## Step 8: Finalize PRD — 2026-07-09T06:06:00.000Z

Done. Summary follows.

## Summary

- PRD.md: 304 lines. PRD_FINALIZED.md: 304 lines. Delta: 0 lines (one line edited inline); ~1 line touched (0.3% of lines modified, no length change).

### Change
- **§3.2 (Catalog) — revise — MenuItem `recipe`** — added that an empty `recipe` list is allowed (item consumes no tracked inventory) — `implementation/app.py:974-989` (empty list accepted after the type check; no non-empty gate).

### Per-edit pre-edit search log

**Edit 1: recipe may be empty**
- (a) Subject: the `recipe` field of a MenuItem — specifically whether an empty list is a valid value. This is the exact PRD-silence the Step 7 fix exposed (impl formerly rejected empty `recipe` with `ERR_INVALID_REQUEST`; the rejection was removed, so impl now accepts it, but PRD never stated whether empty is allowed).
- (b) Impl paths enumerated (grepped `recipe` across `app.py`):
  - `create_menu_item` handler, `app.py:974-1000` — validates `recipe` is a list, iterates entries validating `ingredient_id`/`base_qty`, checks ingredient existence; no non-empty requirement. An empty list passes every check and is stored as `[]`. (Read.)
  - `compute_required_units`, `app.py:503-514` — iterates `mi["recipe"]`; an empty recipe contributes nothing to the required-units map, so downstream inventory/COGS at placement, payment, cancellation, and completion see zero requirement for that item. Consistent — no path crashes or misbehaves on an empty recipe. (Read.)
  - Confirmed no other `recipe` writer or reader exists (grep returned only these two sites plus the creation-handler internals).
- (c) Wording adjustment: chose "an empty recipe list is allowed — such an item simply consumes no tracked inventory" to mirror the existing "(empty is allowed)" convention already used for Ingredient `allergen_tags` in the same paragraph, and to stay descriptive rather than imposing any new constraint on non-empty recipes. Wording does not touch `base_qty`, ordering, or any behavior off the empty-list case, so it introduces no claim inconsistent with the enumerated paths.

No other Step 7 items existed (the single root cause produced all 9 test failures; no test deletions, no test_helpers/ fixes). Nothing else in scope.

## Step 9: Complete PRD — 2026-07-09T06:10:00.000Z (reconstructed record)

> Orchestrator note: Step 9 **did run and did complete** for this task, but the `claude -p` process
> was killed by system memory pressure after `PRD_COMPLETED.md` was written and before this worklog
> entry was appended. The subagent's verbatim summary is therefore lost and cannot be recovered —
> its context was discarded on exit.
>
> Post-hoc verification by the orchestrator (evidence that Step 9 substantively ran, rather than
> dying after its opening `cp`):
>   - `diff workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` → 22 changed lines.
>     (A killed-after-`cp` Step 9 leaves a byte-identical file — that is exactly what happened to
>     task_0569 and task_0571, and both were detected by this diff and re-run. This task was not.)
>   - Edits observed are in-paragraph ambiguity pins consistent with the Step 9 contract, e.g.
>     list-ordering tie-break + filter-parameter semantics (§ listing), configuration-only writes
>     accepted from terminal `CLOSED` and same-status no-op writes (§ store state machine), and
>     spoilage-sweep response being unpaginated and `created_at`-ascending (§ spoilage).
>
> No re-run was performed, because re-running Step 9 over an already-completed Step 9 would diff
> against the already-patched `PRD_COMPLETED.md` and risk compounding edits. The artifact is intact;
> only this log entry was lost.
