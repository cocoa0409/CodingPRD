# Performance Analysis: workspace_task_0002_food_delivery_platform_Opus_4.6_CC_ep04

In isolation, the implementation handles a single end-to-end order correctly (verified by a live curl trace: solo final fee 540, route_group_id None, walks through DELIVERED). All nine failures arise from one underlying defect that compounds across the long-lived server process the test suite runs against.

## Root Causes

### 1. Phantom OFFERED assignments from a no-op uniqueness gate — drives 8/9 failures

`services/dispatch.py::dispatch_order` computes `already_assigned` (the PRD §3.6 precondition that no OFFERED/ACCEPTED/PICKED_UP assignment exists for the order) but never reads the variable. Every call therefore creates a fresh Assignment. `routes/orders.py::start_preparing` always calls `dispatch_order` after the order is already `ACCEPTED`, producing a second `OFFERED` assignment (A2) for the same order, with the same rider, that no test ever accepts or sweeps. When A1 is delivered, `deliver_assignment`'s `has_active_assignments` check (assignments.py:237) finds A2 still in `OFFERED` and refuses to drop the rider back to `AVAILABLE`; the rider is left stranded in `ON_DELIVERY`.

The next test's `take_other_riders_offline` then calls `/api/riders/{id}/go-offline` on that rider — which correctly fails per PRD §3.3 because A2 is still OFFERED — and the fixture silently swallows the error. The stranded rider remains `ON_DELIVERY` for the rest of the session.

### 2. `find_best_rider` ranks the stranded rider above fresh ones — second contract violation, completes the cascade

`services/dispatch.py::find_best_rider` (a) admits both `AVAILABLE` and `ON_DELIVERY` candidates unconditionally, and (b) tie-breaks by `created_at` ascending (older first). With identical default metrics (on_time_rate=1.0, acceptance_rate=1.0), every subsequent cold dispatch picks the older, stranded rider over the freshly-created one. The test's `make_rider_headers(fresh_rider.id)` then fails `assignments.py:42`'s identity check with `ERR_FORBIDDEN: Cannot accept another rider's assignment`. This is what produces the four 403s (`test_accept_cascades_rider_to_on_delivery`, `test_rider_cancel_after_acceptance_creates_no_show_fine`, `test_override_applied_to_entire_subtotal`, `test_settlement_uses_final_commission`).

PRD §3.6 ("opens a dispatch offer to the best available rider") frames ON_DELIVERY participation as a *route-merge* path, not a cold-dispatch path. The impl conflates the two.

### 3. Re-dispatch does not exclude already-ACCEPTED riders — 1 failure

`test_second_accept_same_order_conflicts` re-dispatches an order whose first assignment is already ACCEPTED and asserts the new offer targets a *different* rider. `dispatch_order` only excludes riders in `REJECTED`/`CANCELLED` states for the order, not `ACCEPTED`/`OFFERED`/`PICKED_UP`. The same rider is therefore picked twice, fixture asserts `rider_id != rider_id`.

### 4. Merge-discount + late-fine miscalculations are downstream of #1, not independent

`test_solo_delivery_final_equals_provisional` (405 ≠ 540) and `test_above_thirty_minutes_uses_cap_and_compensation` (905 ≠ 1040) both reduce to the wrong rider being adopted: the stranded rider already carries a `route_group_id` from a prior route-merge test, so its newly-delivered assignment receives the 25% discount, and the late-fine formula (`min(final_fee, 1500) + 500`) then reads 405 instead of 540. Wallet-balance assertions (`test_per_leg_rider_total_is_sum_of_discounted_legs`, `test_deliver_creates_fine_and_debits_wallet_and_recomputes_tier`) read the stranded rider's accumulated balance from prior tests instead of 0 or `final_fee - fine`.

## Model Weaknesses

**Dead validation.** The model wrote the correct precondition check inline (`already_assigned = any(...)`) and then forgot to act on it. A literal reading of PRD §3.6's uniqueness invariant was understood enough to verbalize but not enough to wire into control flow. In black-box testing this is invisible until cross-test state accumulates.

**Local correctness vs. session-level invariant.** The model verified each endpoint against a clean store but did not reason about *resource leaks across requests*: the phantom A2 is the same defect that strands the rider, blocks /go-offline, and pollutes dispatcher inputs. Solving any single one of those symptoms in isolation would not fix the others.

**Conflation of dispatch eligibility.** PRD §3.6 separates "best available rider" (cold dispatch) from "route merging into an existing RouteGroup" (which is what `accept` triggers when an ON_DELIVERY rider takes a nearby new assignment). The impl collapsed the two by making `ON_DELIVERY` riders cold-dispatchable, suggesting the model treated "rider can carry more than one parcel" as license to also offer them new orders directly.

**Tie-break asymmetry.** Choosing `created_at` ascending (oldest wins) for tie-breaking compounds problem #2: even if ON_DELIVERY were filtered out, the older rider would still win identical-metric races, making fresh test fixtures the *least* preferred candidates. PRD does not prescribe a tie-breaker, so either direction is admissible — but the choice that always prefers older state is the worst for a stateful test harness.

## What Passed

105 tests cover auth/RBAC, CRUD, restaurant lifecycle, order placement and validation, the order state machine (independent of rider state), commission tier math, return/refund flow, work-orders, peak-window detection, and validation-pipeline ordering. The arithmetic primitives (`compute_delivery_fee`, `compute_tiered_commission`, `compute_late_fine`, haversine) are correct in isolation; the impl's collapse is concentrated in dispatcher state management.
