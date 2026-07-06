# Project Worklog — task_0731_plant_shop

## Step 1: Create Task Directory — 2026-07-04T11:05:30.000Z

Created tasks/task_0731_plant_shop/ and tasks/task_0731_plant_shop/workspace/ (pre-assigned ID, not reassigned).

## Step 2: Generate Scaffold — 2026-07-04T13:46:30.000Z

## Scaffold Generation — task_0731_plant_shop

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_0731_plant_shop/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0731_plant_shop/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0731_plant_shop/SCAFFOLD_CORNER_DESIGN.yaml`

**Section counts**
- SCAFFOLD.yaml: 15 entities, 6 state machines, 3 concurrency rules, 6 calculations, 19 validations, 52 endpoints, 20 errors, 6 roles
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules × 2 instances = 18 instances (all §0.5 minimums met)
- SCAFFOLD_CORNER_DESIGN.yaml: 26 instances across 9 sections (23 active + 3 excluded_because stubs)

**Lint verdict**
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     23
  Calls scanned (§1.8+§1.9):  323

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Notable design choices**
- Complexity profile: `pricing_engine` × `compliance_audit`; `flat` topology; **parallel** state-machine shape (Order carries independent payment_status × fulfillment_status); `peer_roles` model with two entity-backed roles (Customer, DeliveryDriver) and three opaque operator roles (ShopStaff, Horticulturist, Manager) plus Anonymous.
- Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions, rate_threshold_triggers, selector_policy.
- 3 concurrency rules (OCC on Order, SpecialOrder, StockUnit versions).
- 6 calculations covering both dual-variant (loyalty accrual on Order/Customer domain vs warranty refund on WarrantyClaim domain) and combinatorial complexity across two different modes (delivery-fee tri-condition non-linear branch vs. order-total rounding-order lock).
- Non-linear state machines on two different entities: Order (parallel dimensions) and SpecialOrder (cyclic QUOTED↔RE_QUOTED with revision_count invariant).
- Interval-semantics contrast for Rule 8: Workshop half-open + 15-minute buffer on room resource vs. DeliveryDriver closed intervals + aggregate daily_capacity_minutes.
- Compensating invariants across two different conserved quantities: Customer.points_balance identity via LoyaltyLedger REVERSAL, and per-Plant StockUnit cardinality preservation across warranty return.
- Default logical clock pinned at `2026-03-01T00:00:00Z`; every OCC `expected_*_version` payload references a `${var}` from an earlier capture; every FK carries the canonical `FK -> <Parent>.id` prefix and has a reverse-reachability GET.

## Step 3: Copy INSTRUCTION.md — 2026-07-04T13:47:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-04T13:54:30.000Z

**Summary of PRD generation for task_0731_plant_shop**

**File path:** `/home/ubuntu/github/CodingPRD/tasks/task_0731_plant_shop/workspace/PRD.md`
**Line count:** 311 lines

**Section list:**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles
  - 2.1. Users, Roles, and Access Control
  - 2.2. API Response Structure (verbatim from source)
  - 2.3. Pagination
  - 2.4. Timekeeping and the Logical Clock
  - 2.5. Common Resource Properties
  - 2.6. Monetary Amounts, Rounding, and Precision
  - 2.7. Optimistic Concurrency and Stale-Version Protection
  - 2.8. Validation Priority and Rejection Order
  - 2.9. Cascading Effects and Cross-Entity Consistency
  - 2.10. Nested Resources and Path Parameter Resolution
- §3. Business Logic & Workflows (8 subsections)
  - 3.1. Catalog Composition, Stock Intake, and the Care Log
  - 3.2. Customer Registration and the Order Lifecycle
  - 3.3. Delivery Scheduling, Driver Budgets, and Fulfillment
  - 3.4. Loyalty Accrual, Redemption, and Tier Progression
  - 3.5. Warranty Adjudication and Refunds
  - 3.6. Plant-of-the-Month Subscriptions and Care Reminders
  - 3.7. Workshop Scheduling and Registration
  - 3.8. Special Orders, Repotting Services, and the Re-Quote Cycle
- §4. Endpoint Definitions (52 endpoints; 4-column table Method/Path/Description/Authorized Role(s))
- §5. Error Code Catalogue (20 errors; 2-column table Error ID/HTTP Status Code)

**Coverage numbers:**
- **Entities:** 15 — all named in prose.
- **Endpoints:** 52 in §4 table, matching scaffold count.
- **Errors:** 20 error IDs — all present in §5 table and all mentioned by name at least once in §2 or §3 prose.
- **Roles:** 6 (Anonymous, Customer, ShopStaff, Horticulturist, DeliveryDriver, Manager).
- **State machines:** 6 (Order dual-dimension, Subscription, WarrantyClaim, SpecialOrder incl. cyclic RE_QUOTED, Workshop, DeliveryAssignment).
- **Concurrency rules:** 3 OCC rules (order-cancel, special-order customer-approve, stock-unit adjust) with `expected_<parent>_version` field named and `ERR_STALE_VERSION` (HTTP 412) declared.
- **Calculations:** 6 (loyalty_points_accrual dual-variant, warranty_refund_amount dual-variant, delivery_fee_calculation, order_total_computation pinned step order, subscription_stock_selector, loyalty_tier_evaluation).
- **Validation rules:** 19 priority-ordered rules.

**Zero-silence self-audit:**
- Contract 1 (Field-Name Coverage): PASS.
- Contract 2 (Rule Coverage): PASS — validation priorities, OCC rejections, state-machine transitions with preconditions and side-effects (incl. cross-entity cascades), 6 calculation formulas, sibling-branch symmetry across QUOTED↔RE_QUOTED cycle all rendered in prose.
- Contract 3 (§3 Path Purity): PASS — 0 backtick tokens starting with `/`, 0 bare HTTP-method tokens.
- §2.2: verbatim from source.

## Step 5: Generate Unit Tests — 2026-07-04T14:10:30.000Z

**Test suite generated for task_0731_plant_shop.**

**Test files written (test_suite/):**
- `conftest.py`
- `test_01_pricing_and_calculations.py`
- `test_02_order_lifecycle.py`
- `test_03_loyalty_and_cascades.py`
- `test_04_warranty_workflows.py`
- `test_05_stock_and_shrink.py`
- `test_06_special_orders.py`
- `test_07_workshops_and_deliveries.py`
- `test_08_validation_and_rbac.py`
- `test_09_additional_difficulty_coverage.py`

**Test counts:**
- Queue A (Difficulty): 37 tests across 18 instances (all ≥2 tests, one instance has 3).
- Queue B (Corner): 23 tests across 23 non-stub instances (each ≥1).
- Total: 60 tests.

**Difficulty instances covered (2 each unless noted):**
- Rule 1 dual_variant_calc: loyalty_provisional_vs_final_after_tier_flip; warranty_refund_provisional_vs_final_care_log_deductions (3)
- Rule 2 combinatorial_formula: delivery_fee_zone_heavy_gift_conditional_branch; order_total_rounding_order_pre_tax_redemption
- Rule 3 non_linear_state_machine: order_parallel_dimensions_payment_and_fulfillment_evolve_independently; special_order_cyclic_quoted_re_quoted
- Rule 4 transitive_cascade: delivery_deliver_cascade_depth_3_order_stock_customer; warranty_approve_cascade_depth_2_orderline_stock_customer_wallet
- Rule 5 priority_pair_validation_conflict: state_vs_business_fiscal_special_order_re_quote_from_re_quoted; business_safety_vs_business_referential_warranty_expired_and_not_owner
- Rule 6 boundary_precision_check: warranty_period_boundary_exact_day_inclusive; subscription_stock_selector_empty_candidate_set_flips_missing_stock
- Rule 7 cross_entity_state_dependency: delivery_deliver_requires_order_paid; warranty_submit_requires_order_delivered
- Rule 8 resource_temporal_overlap: workshop_room_half_open_with_15min_buffer; delivery_driver_closed_interval_and_daily_capacity_aggregate
- Rule 9 compensating_invariant: order_cancel_preserves_customer_points_balance_invariant; warranty_approve_preserves_stockunit_cardinality_invariant

**Corner instances covered:** all 23 non-stub instances across entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers.

**Corner stubs NOT translated (owned by cited difficulty instance):**
- entities/care_log_entry_immutable_no_common_fields → transitive_cascade/warranty_approve_cascade_depth_2_orderline_stock_customer_wallet
- calculations/loyalty_tier_evaluation_exact_500_flips_bronze_to_silver → transitive_cascade/delivery_deliver_cascade_depth_3_order_stock_customer
- consistency_model/immediate_visibility_of_order_total_in_create_response → combinatorial_formula/order_total_rounding_order_pre_tax_redemption

**Instances skipped for PRD non-uniqueness:** None. Two tests use `validate_error_is_one_of` where PRD names two acceptable error_ids (special-order requote-from-REQUESTED: ERR_INVALID_STATE vs ERR_SPECIAL_ORDER_INVALID_STATE; warranty submit on non-delivered order: ERR_INVALID_STATE vs ERR_WARRANTY_NOT_ELIGIBLE) — legitimate PRD-precedence gaps, not skips.

**test_helpers/ modules created:**
- `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

## Step 6: Generate Implementation — 2026-07-04T14:10:30.000Z

**Files written under `implementation/`:**

- `start.sh` (11 LOC) — guarded pip install (`if ! python3 -c "import flask"`) then `exec python3 app.py`; `cd "$(dirname "$0")"` at top; foreground; PORT-aware; executable.
- `requirements.txt` — `flask==3.0.3`.
- `app.py` (~55 LOC) — Flask factory, registers 10 blueprints, `ApiError` handler → standard error envelope, 404/405/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), use_reloader=False, threaded=True)`; no seeding/module-level entity population.
- `clock.py`, `errors.py`, `db.py`, `response.py`, `middleware.py` — clock/error/store/envelope/auth-context modules.
- `services/common.py`, `loyalty.py`, `pricing.py`, `inventory.py`, `validation.py`.
- `routes/clock.py`, `customers.py`, `plants.py`, `drivers.py`, `orders.py`, `deliveries.py`, `subscriptions.py`, `workshops.py`, `warranty.py`, `special_orders.py` — 52 endpoints.

**Entities/endpoints implemented:** all 15 entities; all §1.5 endpoints incl. `/_clock/set_current_utc` and `/_scheduler/fulfill-subscriptions`.

**State machines implemented:**
- Order parallel dims (payment × fulfillment).
- Subscription ACTIVE ⇄ PAUSED ⇄ MISSING_STOCK, → CANCELLED.
- WarrantyClaim SUBMITTED → APPROVED with full cascade / DENIED.
- SpecialOrder REQUESTED → QUOTED ⇄ RE_QUOTED, → CUSTOMER_APPROVED (OCC, revision_count cap 3).
- Workshop SCHEDULED → COMPLETED (cascades REGISTERED → ATTENDED).
- DeliveryAssignment SCHEDULED → DELIVERED (drives Order → DELIVERED+PAID and loyalty finalization).

**Calculations:** delivery_fee_calculation, order_total_computation (pinned 4 steps), loyalty_points_accrual provisional/final, warranty_refund_amount provisional/final, subscription_stock_selector, loyalty_tier_evaluation.

**Validations enforced in priority order:** auth (401) → RBAC/ownership (403) → existence (404) → shape (400) → state (409) → OCC (412) → business_safety (422) → business_temporal (409/422) → business_referential (409/422) → business_fiscal (402/409/422).

**OCC:** expected_order_version on cancel, expected_special_order_version on customer-approve, expected_stock_unit_version on adjust — all 412 ERR_STALE_VERSION.

**start.sh wiring:** `#!/usr/bin/env bash`, `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded deps, `exec python3 app.py`. `app.py` reads PORT env var (default 10000), binds 0.0.0.0, disables reloader/debug, threaded on.

**Smoke tested:** boots in <1s cold, empty state; register/plant/stock/order/pay/dispatch/OCC-cancel flow, delivery-fee clamp, tax rounding, ERR_WORKSHOP_OVERLAP with 15-min buffer, ERR_STALE_VERSION — all responses use exact PRD §2.2 envelope.

## Step 7: Test/Diagnose/Fix Loop — 2026-07-04T14:20:00.000Z

All 8 rounds pass 60/60.

- Iterations run: 2 (initial diagnostic sweep, then 8-round confirmation sweep after fixes).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`:
  - `test_suite/test_07_workshops_and_deliveries.py` (`TestDeliveryDriverDailyCapacity.test_third_dispatch_exceeding_daily_capacity_rejected`) — the fixture set `daily_capacity_minutes=180` and then dispatched three 60-minute windows summing to exactly 180 minutes; PRD §3.3 says the sum "must not exceed" the driver's capacity, so 180 ≤ 180 is legally allowed and the assertion could never fire. Changed capacity to 179 so the third dispatch (total 180) genuinely exceeds it. Arithmetic-only fixture bug (STEP 2).
- Fixes applied to `implementation/`:
  - `implementation/routes/deliveries.py` (`deliver`) — final-accrual tier snapshot was reading `customer["loyalty_tier"]` directly, which already reflected this very order's own provisional accrual. PRD §3.4: "the customer's tier AS OBSERVED at the pre-cascade snapshot of delivery (so a tier flip that would be caused by this very order's own accrual does not apply to this order's own accrual)". Fix subtracts `order.points_provisional` from `lifetime_points_earned` before re-evaluating the tier for the final accrual, so a 45000-cent seed + 5000-cent trigger order finalizes at lifetime=500 in BRONZE (not 525 in SILVER).

## Step 8: Finalize PRD — 2026-07-04T14:25:00.000Z

- **Line counts:** PRD.md = 311 lines, PRD_FINALIZED.md = 311 lines. **Delta: 0 lines (0.0%).**

**Per-change bullets:** *(none)*

Both Step 7 items were classified as non-PRD-silences/non-mismatches after inspecting both PRD.md and the current `implementation/`:

1. **Test fixture arithmetic bug** (`test_suite/test_07_workshops_and_deliveries.py`, `TestDeliveryDriverDailyCapacity`): PRD §3.3 says the daily minutes total "must not exceed" `daily_capacity_minutes`. `implementation/routes/orders.py:353` implements this as a strict `>` — a boundary sum of exactly `daily_capacity_minutes` is legally allowed. The fixture erroneously scheduled 180 min against a 180 min cap and expected rejection. PRD.md and impl already agree; only the fixture arithmetic was wrong. **No PRD silence, no impl-vs-PRD mismatch, no PRD edit required.**

2. **Final-accrual tier snapshot** (`implementation/routes/deliveries.py:38-51`, `deliver`): PRD §3.4 already pins the rule verbatim — "the customer's tier AS OBSERVED at the pre-cascade snapshot of delivery (so a tier flip that would be caused by this very order's own accrual does not apply to this order's own accrual)". The Step 7 impl fix subtracts `order.points_provisional` from `Customer.lifetime_points_earned` before re-evaluating the tier for the final accrual. This brought the impl **into conformance** with pre-existing PRD prose. **No PRD silence, no PRD-mismatch remaining, no PRD edit required.**

**Per-edit pre-edit search log:**

- **Edit #1 (workshops/deliveries fixture item):**
  - (a) Subject: driver daily-capacity boundary semantics (`>` vs `≥`) in PRD §3.3.
  - (b) Enumerated impl paths: `implementation/routes/orders.py` `dispatch_order` — line 353 (`total_minutes_day + proposed_minutes > driver["daily_capacity_minutes"]`); grep confirms the daily-capacity comparison lives only in `dispatch_order`. PRD §3.3 sentence "the sum... must not exceed the driver's `daily_capacity_minutes`" already matches strict-`>` impl.
  - (c) Wording adjustment: none.

- **Edit #2 (deliveries final-accrual tier snapshot item):**
  - (a) Subject: pre-cascade tier snapshot for the ACCRUAL_FINAL_DELTA at delivery finalization in PRD §3.4.
  - (b) Enumerated impl paths: `implementation/routes/deliveries.py` `deliver` — lines 38-51 and 67; `implementation/services/loyalty.py` `compute_accrual_points`, `TIER_MULT`, `TIER_THRESHOLDS`, `_re_evaluate_tier`; `implementation/routes/warranty.py` `approve_claim` line 153 (separate site). PRD §3.4 already says "as observed at the pre-cascade snapshot of delivery" verbatim.
  - (c) Wording adjustment: none.

## Step 9: Complete PRD — 2026-07-04T14:39:00.000Z

- Source: `PRD_FINALIZED.md` (311 lines, 55091 chars) → `PRD_COMPLETED.md` (311 lines, 57422 chars). Char delta: +2331. Line count unchanged (all edits are in-paragraph inserts/revisions).
- Counts: 4 ambiguity-pins, 5 mismatch-revisions.

Changes:
- §3.2 (checkout stock-unit selection) — revise — ambiguity — pinned that `qty` units are reserved per line, `OrderLine.stock_unit_id` is stamped from the first (oldest) reserved unit, remaining reserved units tracked internally for cascade — `implementation/routes/orders.py:104-165`
- §3.3 (dispatch overlap/capacity) — revise — ambiguity — pinned that overlap check filters by `SCHEDULED`/`DELIVERED` only (FAILED excluded); minute count is `floor((end−start seconds)/60)` — `implementation/routes/orders.py:334-354`
- §3.3 (delivery finalization cascade) — revise — mismatch/ambiguity — pinned that every reserved stock unit under each OrderLine flips `RESERVED`→`SOLD` (not just the publicly exposed `stock_unit_id`); each stock unit's `version` bumps; `delivered_at` is stamped per line for the warranty-window computation — `implementation/routes/deliveries.py:56-65`
- §3.4 (warranty-approval reversal tier) — revise — mismatch — pinned that reversal uses `Customer.loyalty_tier` observed at approval time, not at original delivery — `implementation/routes/warranty.py:153, 171`
- §3.5 (warranty submission preconditions) — revise — ambiguity — pinned that a line whose parent order is not yet `DELIVERED` fails as `ERR_INVALID_STATE` (state precondition); clarified warranty-expiry evaluates before ownership-referential — `implementation/routes/warranty.py:54-68`
- §3.5 (approval cascade) — revise — mismatch — pinned that stock unit's `version` bumps twice (once per `SOLD`→`RETURNED` and `RETURNED`→`SHRINK` transition), not once; noted approval instant is stamped for the 30-day window — `implementation/routes/warranty.py:163-168, 157`
- §3.5 (30-day fiscal window) — revise — ambiguity — pinned that a prior approved claim is in-window when its own approval instant ≥ `logical_clock − 30 days` — `implementation/routes/warranty.py:132-147`
- §3.6 (scheduler on-hit cascade) — revise — ambiguity — pinned that the auto-created order gets `fulfillment_status=PENDING`, the stock unit is reserved (not sold), and `ACCRUAL_PROVISIONAL` is appended; also pinned that `next_fulfillment_at` advances by adding 30 days to its previous stored value (not to the current clock) — `implementation/routes/subscriptions.py:196-241`
