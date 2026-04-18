# Performance Analysis: workspace_task_0002_food_delivery_platform_Opus_4.6_CC_ep01

**Result: 102/114 (89.5%)**

## Root Causes

### 1. Dispatcher tie-breaker reuses one rider across the whole test session — 11 of 12 failures

`find_best_rider_for_order` / `create_dispatch_for_order` (app.py:451–520) sort AVAILABLE candidates by `created_at` ascending and always pick index 0. PRD §3.6 says the system picks "the best available rider" but prescribes no ordering; the model invented a deterministic oldest-first rule. Because the rider pool is never reset between tests, the very first rider the server sees keeps winning every dispatch, and their state (wallet, offer/delivery history, lingering ACCEPTED assignments, fine rows) accumulates for the entire session. Every downstream failure traces to this one choice:

| Symptom | Cascade |
|---|---|
| `accept_assignment` returns 403 (4 tests: `test_accept_cascades_rider_to_on_delivery`, `test_rider_cancel_after_acceptance_creates_no_show_fine`, `test_override_applied_to_entire_subtotal` setup, `test_settlement_uses_final_commission` setup) | Test creates a fresh rider and calls `make_rider_headers(fresh_rider.id)`, but dispatch stamps the old reused rider → `uid != a["rider_id"]` → `ERR_FORBIDDEN` (app.py:1568). `take_other_riders_offline` cannot neutralize this because the reused rider is typically ON_DELIVERY with an ACCEPTED peer from a prior test, and go-offline is blocked by PRD §3.3. |
| Solo `final_delivery_fee_cents` = 405 not 540 (1 test) | All test restaurants share the reference coords, so haversine=0. The reused rider still carries an ACCEPTED peer assignment, so `assignment_accept`'s merge block (app.py:1592–1615) attaches the "solo" order to a route group with ≥2 members → deliver applies the 25% floor discount (app.py:1727–1729). |
| Tier-3 late fine = 905 not 1040 (1 test) | `min(final_fee, 1500) + 500` with `final_fee=405` from the same mis-merge yields `min(405,1500)+500 = 905`. |
| Rider `wallet_balance_cents` mismatches (2 tests: `test_rider_wallet_net_credit_minus_late_fine` got 3030 vs -595; `test_per_leg_rider_total_is_sum_of_discounted_legs` got 3645 vs 810) | Wallet balance is the running sum of every credit/debit the reused rider ever incurred — not the per-delivery delta the assertions expect. |
| `bonus_tier` = BRONZE not PLATINUM (2 tests) | After ≥10 accumulated deliveries, `on_time_rate` is recomputed from the real window and the reused rider's long history of late deliveries from tests 07/08 drags the score under 0.70. Fresh-rider seed (app.py:876 `"bonus_tier": "BRONZE"`) also fails to call `compute_bonus_tier` at creation, but the recompute on delivery would have corrected it if history were clean. |
| Fine count 7 not 1 (1 test) | Same reused rider is the subject of every LATE_DELIVERY fine produced earlier in the run. |

### 2. `/api/orders/{id}/dispatch` refuses re-dispatch when a prior assignment is ACCEPTED — 1 failure

`test_second_accept_same_order_conflicts` setup fails 409. app.py:1302–1305 rejects `/dispatch` if any assignment for the order is in {OFFERED, ACCEPTED, PICKED_UP}. PRD §4 explicitly names `/dispatch` as "Trigger or re-trigger dispatch of a fresh assignment" and PRD §3.6 locates the uniqueness invariant on accept, not dispatch — the server must be able to create a fresh OFFERED while an ACCEPTED peer exists so the second rider's /accept is the thing that trips `ERR_ORDER_ALREADY_ASSIGNED`.

## Model Weaknesses

**Fills silence with a concrete rule instead of a neutral one.** PRD §3.6 gives no tie-breaker among `AVAILABLE` riders. The model invented "oldest-first", which is deterministic (a virtue in isolation) but turns every dispatch in the session into the same rider. A reasonable inference would be that a selection policy which concentrates load on one rider contradicts PRD §3.3's fairness signals (`acceptance_rate`, `on_time_rate`, `bonus_tier` recomputed per rider) — those metrics only make sense if dispatch distributes load. Silence on the tie-breaker is not silence on the goal.

**Invariant over-promotion.** §3.6's uniqueness rule is a post-condition of accept, not a pre-condition of dispatch; §4 explicitly calls `/dispatch` "Trigger or re-trigger… a fresh assignment", which only coheres if dispatch is allowed while a peer is ACCEPTED. The model lifted a constraint from one transition into an adjacent one without reading whether the surrounding prose supported it — a systematic failure to cross-reference.

**Register-time defaults not run through the compute function.** `bonus_tier` is hard-coded to `"BRONZE"` at rider creation instead of `compute_bonus_tier(1.0, 1.0, 5.0)`, which would yield PLATINUM given the PRD-stated seed metrics. The PRD specifies the formula and the seed values; wiring a literal in parallel to the formula is a direct self-contradiction the model did not catch.

## What Passed

102 of 114 tests pass (89.5%), covering the full CRUD surface, restaurant lifecycle (approve/suspend/reinstate/settle), order placement and state machine, return/refund cascade, work-order assign/resolve/close gating, provisional and tiered-commission arithmetic, tier-1 and tier-2 late fines, all validation-priority scenarios, and the RBAC/identity matrix. The passing set implies the entity model, serializers, per-request authorization, and short single-session workflows are correct — every failure is a cross-request interaction or a state-machine edge where the model replaced PRD-prescribed ambiguity with a harmful concrete rule.
