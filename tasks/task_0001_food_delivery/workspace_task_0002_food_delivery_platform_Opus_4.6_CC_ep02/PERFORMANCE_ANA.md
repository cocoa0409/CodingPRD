# Performance Analysis: workspace_task_0002_food_delivery_platform_Opus_4.6_CC_ep02

**Result: 102/114 (89.5%)**

## Root Causes

### 1. Dispatch picks the wrong rider — 10 of 12 failures

`routes/orders.py::find_best_available_rider` returns the first rider whose status is `AVAILABLE` **or** `ON_DELIVERY`, with no exclusion for riders already holding an `ACCEPTED`/`PICKED_UP` assignment for the same order. The PRD treats dispatch as targeting a free rider, and the test harness carefully creates a *fresh* rider per test and takes every other session rider offline before dispatching. Because the impl happily re-picks a stale `ON_DELIVERY` rider from a prior test:

- **Identity-mismatch 403 (4 tests)** — `test_accept_cascades_rider_to_on_delivery`, `test_rider_cancel_after_acceptance_creates_no_show_fine`, `test_override_applied_to_entire_subtotal` (setup), `test_settlement_uses_final_commission` (setup). The test builds headers with `make_rider_headers(fresh_rider.id)` but the server stamped `assignment.rider_id` with a stale rider, so the ownership check rejects.
- **False route-merge (3 tests)** — `test_solo_delivery_final_equals_provisional` (405 vs 540), `test_per_leg_rider_total_is_sum_of_discounted_legs` (4185 vs 810), `test_above_thirty_minutes_uses_cap_and_compensation` (905 vs 1040). When dispatch re-uses a rider that still has an `ACCEPTED` peer, `try_route_merge` (assignments.py:72) finds it, builds a RouteGroup, and applies the 25% discount to a supposedly solo order. Downstream late-fine math in `compute_late_fine` then reads the discounted fee and produces 905 (= min(405,1500)+500) instead of 1040.
- **Stale rider state (3 tests)** — `test_deliver_creates_fine_and_debits_wallet_and_recomputes_tier` (7 fines vs 1), `test_new_rider_completing_on_time_remains_platinum` (BRONZE), `test_rider_wallet_net_credit_minus_late_fine` (3570 vs −595). Tests assume a clean wallet/fine history for their rider; they inherit another test's rider carrying prior fines and degraded metrics.
- **Re-dispatch uniqueness (1 test)** — `test_second_accept_same_order_conflicts`. The impl dispatches without excluding the rider that already holds an `ACCEPTED` assignment for that order, so the re-dispatched assignment carries the same `rider_id`.

### 2. Platinum boundary — 1 failure

`test_platinum_at_inclusive_0_90_threshold` expects `PLATINUM` at score ≥ 0.90. The impl's `compute_bonus_tier` boundary is correct (`>= 0.90`), but `compute_rider_score` quantizes to 3 decimals via `ROUND_HALF_UP`, which for the specific boundary construction can fall into `SILVER` once the test's synthetic metric history is routed onto the (stale) rider. Likely masked by #1 rather than an independent bug.

## Model Weaknesses

**Defaults to the loosest filter when a rule is not spelled out.** The PRD's silence on tie-breakers is a reasonable product choice, but silence is not a license for a permissive candidate pool. The impl admits both `AVAILABLE` and `ON_DELIVERY` riders into dispatch wholesale, even though PRD §3.6 only allows `ON_DELIVERY` re-targeting inside the narrow route-merge window (≤500 m, live route). A model that reasons from the spec would notice the conditional and keep the default pool = `AVAILABLE`; this one generalized the exception into the rule.

**Fails to derive invariants that follow directly from stated rules.** PRD §3.6 states that only one `OFFERED/ACCEPTED/PICKED_UP` assignment can exist per order — "dispatch must not re-select a rider who already holds an active assignment for this order" is a direct corollary, not a new requirement. The impl even wired an `exclude_rider_ids` hook into `create_dispatch_assignment`, but `dispatch_order` calls it without populating the set. The plumbing exists; the inferential step from uniqueness rule → exclusion set was skipped.

**Unscoped cascade triggers.** `try_route_merge` scans *any* `ACCEPTED` peer the rider holds, with no check that the peer belongs to the same dispatch context (same route, same merge window). Route-merging is described in PRD as a scoped optimization; treating its trigger as global means the discount fires on unrelated prior assignments once state leaks across tests — a failure mode specific to benchmark suites that reuse entities.

## What Passed

All auth/RBAC, CRUD, restaurant lifecycle, order placement validation, single-order state machine, provisional fee/commission, return/refund flows, work-order lifecycle, and most rider-lifecycle tests passed (102/114). Every passing path exercises endpoints where the rider identity is either irrelevant or freshly created within the same call; every failing path either depends on dispatch picking the *intended* rider or on that rider's history being clean. The impl's formulas (haversine, tiered commission, late-fine tiers, floor-discount arithmetic) are correct in isolation — the fault is at the dispatch-selection seam, not in the business math.
