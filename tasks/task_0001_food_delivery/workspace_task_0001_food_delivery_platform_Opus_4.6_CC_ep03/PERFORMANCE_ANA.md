# Performance Analysis: workspace_task_0002_food_delivery_platform_Opus_4.6_CC_ep03

**Result: 105/114 (92.1%)**

## Root Causes

### 1. Dispatch is not merge-aware — 7 of 9 failures

`services/dispatch_service.py::find_best_rider` filters to `{AVAILABLE, ON_DELIVERY}` riders, sorts by `created_at`, and *strictly prefers* any `AVAILABLE` candidate over any `ON_DELIVERY` one. Route-merging (PRD §3.6) is then attempted post-hoc inside `try_merge_route`, but only fires if the *same* rider already holds an `ACCEPTED` peer — i.e., only if dispatch happened to pick that rider. The two behaviors contradict each other: to merge, the second leg must be offered to the `ON_DELIVERY` rider whose current route pickup is within 500 m, yet the selector will unconditionally divert to any `AVAILABLE` rider instead. As soon as a stray `AVAILABLE` rider from earlier in the session is around, merging becomes structurally impossible. This fails all 5 merged-delivery tests in test_06/test_12 (with identical `a2.rider_id='3be4247b-…'` — one persistent stray across tests) and spills into 2 identity-mismatch 403s (`test_accept_cascades_rider_to_on_delivery`, `test_rider_cancel_after_acceptance_creates_no_show_fine`) where the test's fresh rider is passed over in favor of the stray, so `make_rider_headers(fresh.id)` no longer matches `assignment.rider_id`.

### 2. `/api/orders/{id}/dispatch` forbids re-dispatch while an ACCEPTED peer exists — 1 failure

`routes/orders.py::manual_dispatch` (line 195-199) rejects with `ERR_ORDER_ALREADY_ASSIGNED` whenever any assignment is in `{OFFERED, ACCEPTED, PICKED_UP}`. `test_second_accept_same_order_conflicts` setup is blocked on exactly this path. PRD §4 describes `/dispatch` as "Trigger or re-trigger dispatch of a fresh assignment" and locates the uniqueness invariant on `/accept`, not `/dispatch` — the whole point of re-dispatch is to seed the race that `/accept` will resolve.

### 3. PLATINUM boundary — 1 failure, masked by #1

`test_platinum_at_inclusive_0_90_threshold` expects a fresh rider after one on-time delivery to land on `PLATINUM` (score 1.000). The impl's formula is correct (`compute_bonus_score` + `score_to_tier` with inclusive `>=0.90`), but the test's `run_order_to_delivered` adopts whichever rider dispatch stamped; the stray rider from root cause #1 arrives with enough history to drop the score into `GOLD`.

## Model Weaknesses

**Post-hoc mechanisms instead of selection-time policy.** PRD §3.6 describes merging as a conditional cascade, but achieving it requires the *selector* to prefer a nearby `ON_DELIVERY` rider over a distant `AVAILABLE` one when a merge is possible. The model implemented the cascade faithfully and the selector independently, never connecting them — so the code runs the logic in the wrong order (pick rider → try merge) when the spec implies (detect merge opportunity → pick merge-eligible rider).

**Invariant over-promotion across transitions.** The §3.6 "no other Assignment in OFFERED/ACCEPTED/PICKED_UP" clause is a post-condition of `/accept`; the model hoisted it into `/dispatch` as a pre-condition. Reading §4's explicit "re-trigger dispatch" language together with §3.6 would have revealed the two are meant to compose (dispatch seeds, accept arbitrates). Lifting a state-machine invariant one transition too early breaks that composition.

**Symmetric treatment of rider-status categories.** The selector treats `ON_DELIVERY` riders as a strict fallback below `AVAILABLE`. This is intuitive but ignores the PRD's qualitative distinction: `ON_DELIVERY` is the *only* status from which merging can occur. A model that tracks not just what the statuses are but what they enable would have kept merge-eligible `ON_DELIVERY` riders on the primary track under the right geometric condition.

## What Passed

All auth/RBAC, CRUD, restaurant lifecycle, order placement and state machine, provisional/tiered/flat commission (including settlement), solo delivery fee, all late-fine tiers, the return/refund cascade with escalation, and every work-order flow pass — 105 tests. Every failure is concentrated at the dispatch seam or at downstream assertions that depend on dispatch picking the correct rider. The business arithmetic, serialization, RBAC, and single-actor state machines are sound; the gap is in how dispatch negotiates between "free rider" and "merge-eligible busy rider", and in drawing a boundary between dispatch's and accept's responsibilities.
