# Performance Analysis: workspace_task_0001_food_delivery_platform_Opus_4.6_CC_ep04

**Result: 106/114 (93.0%)**

## Root Causes

### 1. Fresh riders are born `bonus_tier="BRONZE"` instead of deriving the tier from their default metrics — all 8 failures cascade from this

`models/rider.py` hard-codes `self.bonus_tier = "BRONZE"` in `__init__`, while the tier rule in PRD §3.3 ("a score of 0.90 or more is PLATINUM") puts a rider with the default metrics (`on_time_rate=1.0`, `acceptance_rate=1.0`, `rating=5.0`, score = 1.000) squarely in PLATINUM. The dispatcher (`services/dispatch.py:31`) sorts AVAILABLE/ON_DELIVERY candidates by `(tier, -acceptance_rate, created_at)`. That makes any rider who has completed one on-time delivery — and is thus promoted to PLATINUM by `recompute_bonus_tier` — strictly outrank every freshly created BRONZE rider in all later tests. Tests that create a new rider and call `take_other_riders_offline` to narrow the pool cannot always succeed: `go-offline` is legally rejected for riders still holding active assignments (`routes/riders.py:69–74`), so stale PLATINUM riders with leftover ACCEPTED/PICKED_UP state stay in the pool and keep winning dispatch.

The stale-rider cascade then manifests four ways:

| Failure cluster | Mechanism |
|---|---|
| 403 `"Cannot accept another rider's assignment"` on `/accept` (4 tests) | Test sends headers with the fresh rider's id, but `assignment.rider_id` is the stale PLATINUM rider — `routes/assignments.py:39` rejects. Hits `test_accept_cascades_rider_to_on_delivery`, `test_rider_cancel_after_acceptance_creates_no_show_fine`, and the two commission-override tests via their shared setup. |
| Merge discount applied to a solo delivery (`test_solo_delivery_final_equals_provisional`, got 405 vs. 540) | Stale rider still holds a prior ACCEPTED/PICKED_UP assignment. `try_merge_route` (`services/dispatch.py:44`) finds it, and because every test restaurant is built at the same `REFERENCE_LAT/LNG` (`test_helpers/factories.py:18`), the 500 m check in the merge rule is always satisfied. A RouteGroup of size ≥ 2 forms, `is_merged=True` at delivery, and 540 − floor(540 · 0.25) = 405 is returned. |
| Inflated rider wallet (`test_per_leg_rider_total_is_sum_of_discounted_legs` 4185 vs. 810; `test_deliver_creates_fine_and_debits_wallet_and_recomputes_tier` 9800 vs. −595) | The adopted stale rider carries accumulated `wallet_balance_cents` from prior tests; the test's invariant assumes a zero starting balance. |
| `test_platinum_at_inclusive_0_90_threshold` got GOLD vs. PLATINUM | Stale rider has REJECTED offers in their history, pulling `acceptance_rate` below 1.0 just enough for the composite score to drop into the [0.80, 0.90) GOLD band. |

### 2. `find_best_available_rider` treats ON_DELIVERY riders as dispatch-eligible (`dispatch.py:26`)

Compounds #1. Once a stale rider transitions to ON_DELIVERY and holds residual assignments (so they cannot be taken offline), they remain a first-rank candidate for subsequent dispatches, keeping the cycle going across tests.

### 3. `try_merge_route` has no scope bound beyond the 500 m pickup-distance check

No temporal cutoff, no "same session / same dispatch wave" guard. Any stale ACCEPTED assignment on the same rider at a shared-coordinate restaurant silently co-opts the new assignment into a RouteGroup (see solo-delivery symptom above).

## Model Weaknesses

**Derived state initialized as a constant.** The model treats `bonus_tier` as storage rather than a projection of metrics, so the birth-time value contradicts the rule the same model enforces moments later. Field-level consistency is preserved only incidentally — when a code path happens to recompute — and fails at boundaries (new entities, reads before the first triggering event).

**Assuming single-test isolation in a persistent in-memory store.** The implementation stores riders, assignments, and route groups in process-level dicts shared by all tests in a session, but writes code as if every call starts from a clean slate. Dispatch and merge logic never consider that adversarial leftovers might exist, so they compose incorrectly with residual state.

**Priority scheduler that lacks deterministic tie-breakers and starves unranked entrants.** The `(tier, −acceptance_rate, created_at)` sort is strictly lexicographic, so any entity with even one real metric dominates all bootstrapping entities forever. The PRD explicitly declines to mandate a tie-breaker, so the model could have chosen a round-robin or recency-favoring order but instead built a monotonic-preference loop.

## What Passed

106 passing tests cover authentication, RBAC, CRUD for every entity, restaurant lifecycle (including approval and tiered pricing), order placement and validation, the main order state machine, commission tier math on the default path, no-show/late-fine arithmetic where the test does not read the rider's wallet across tests, returns and refund flows, and work-order orchestration. The implementation is broadly contract-correct; the defects are concentrated in rider lifecycle (initial tier derivation), dispatch scheduling (tier-priority starvation), and the implicit cross-test state leak through RouteGroup merging.
