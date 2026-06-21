"""Depth tests for validation-priority precedence (PRD-stated only), resource temporal
overlap, and compensating conserved-quantity invariants (PRD §2.6, §2.10, §3.2, §3.3,
§3.6, §3.8).

NOTE: the clearance-before-crew precedence instance is intentionally not translated —
PRD §3.3 narrates the clearance and crew checks but never states that clearance is
evaluated before the crew-window check, so that precedence is not uniquely PRD-derivable.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_delivery_job_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ── Rule 5: priority_pair_validation_conflict / state_beats_fiscal_on_reserve ──

def test_reserve_already_reserved_empty_pool_returns_invalid_state(api):
    """PRD §2.10: "Only after those four universal gates pass does the system evaluate
    referential business checks, then state-machine preconditions, then optimistic-
    concurrency, then the domain-specific safety and fiscal rules." PRD §3.2: "Reservation
    advances `lifecycle_status` from `QUOTED` to `RESERVED` and is permitted only when the
    agreement is `QUOTED`; an agreement in any other lifecycle state is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve
    """
    # Single unit pool: reserve once (pool now empty, agreement RESERVED), then reserve the
    # SAME agreement again. State precondition (not QUOTED) precedes the fiscal inventory
    # floor, so ERR_INVALID_STATE wins over ERR_NO_INVENTORY.
    F.set_clock()
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="NONE")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="pri5a@x.com")
    ag = F.create_agreement(cust["id"], depot["id"], size_code="C16", protection_tier_code="NONE")
    reserved = validate_success(
        api.reserve_agreement(ag["id"], {"expected_agreement_version": ag["version"]}, DO), 200)

    res = api.reserve_agreement(
        ag["id"], {"expected_agreement_version": reserved["version"]}, DO)
    validate_error(res, "ERR_INVALID_STATE")


def test_reserve_state_check_precedes_inventory_floor_status_code(api):
    """PRD §3.2: "There must also be stock: if the matching inventory row's
    `available_units` is below 1, the reserve is rejected with `ERR_NO_INVENTORY` rather
    than driving the pool negative." PRD §2.10: "a deeper business failure can never mask a
    shallower one."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve
    """
    F.set_clock()
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="NONE")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="pri5a2@x.com")
    ag = F.create_agreement(cust["id"], depot["id"], size_code="C16", protection_tier_code="NONE")
    reserved = validate_success(
        api.reserve_agreement(ag["id"], {"expected_agreement_version": ag["version"]}, DO), 200)

    res = api.reserve_agreement(
        ag["id"], {"expected_agreement_version": reserved["version"]}, DO)
    assert res.status_code == 409  # ERR_INVALID_STATE, not the also-true ERR_NO_INVENTORY


# ── Rule 8: resource_temporal_overlap / crew_halfopen_plus_buffer_overlap ──

def _world_two_units_one_crew(email):
    F.set_clock()
    F.create_container_model(size_code="C16")
    F.create_protection_plan(tier_code="NONE")
    depot = F.create_depot()
    inv = F.create_depot_inventory(depot["id"], size_code="C16", total_units=2)
    crew = F.create_crew(depot["id"])
    cust = F.create_customer(email=email)
    return {"depot": depot, "inventory": inv, "crew": crew, "customer": cust,
            "plan": {"tier_code": "NONE"}}


def test_crew_buffered_window_overlap_rejected(api):
    """PRD §3.3: "the proposed window, extended at its tail by the crew's
    `setup_buffer_minutes`, must not overlap any other `SCHEDULED` job on the same crew ...
    the new job's similarly buffered interval must share no instant with any of them; an
    overlap is rejected with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_halfopen_plus_buffer_overlap
    """
    # Job A [09:00,11:00) + 30min buffer -> occupies through 11:30; job B at 11:15 collides.
    world = _world_two_units_one_crew("crw@x.com")
    ag1, unit1 = F.create_quoted_then_reserved(world, agreement_overrides={"site_address": "A St"})
    validate_success(api.create_delivery_job(
        create_delivery_job_payload(ag1["id"], world["crew"]["id"], unit1["id"],
                                    window_start="2026-07-16T09:00:00Z",
                                    window_end="2026-07-16T11:00:00Z"), DO), 201)
    ag2, unit2 = F.create_quoted_then_reserved(world, agreement_overrides={"site_address": "B St"})

    res = api.create_delivery_job(
        create_delivery_job_payload(ag2["id"], world["crew"]["id"], unit2["id"],
                                    window_start="2026-07-16T11:15:00Z",
                                    window_end="2026-07-16T12:15:00Z"), DO)
    validate_error(res, "ERR_CREW_WINDOW_CONFLICT")


def test_crew_window_after_buffer_boundary_allowed(api):
    """PRD §3.3: "treating each existing scheduled job's occupied interval as its
    `[window_start, window_end)` window plus the buffer minutes appended after `window_end`,
    the new job's similarly buffered interval must share no instant with any of them".

    Design: Difficulty/resource_temporal_overlap/crew_halfopen_plus_buffer_overlap
    """
    # Job A occupies through exactly 11:30; a job B starting exactly 11:30 shares no instant.
    world = _world_two_units_one_crew("crw2@x.com")
    ag1, unit1 = F.create_quoted_then_reserved(world, agreement_overrides={"site_address": "A St"})
    validate_success(api.create_delivery_job(
        create_delivery_job_payload(ag1["id"], world["crew"]["id"], unit1["id"],
                                    window_start="2026-07-16T09:00:00Z",
                                    window_end="2026-07-16T11:00:00Z"), DO), 201)
    ag2, unit2 = F.create_quoted_then_reserved(world, agreement_overrides={"site_address": "B St"})

    res = api.create_delivery_job(
        create_delivery_job_payload(ag2["id"], world["crew"]["id"], unit2["id"],
                                    window_start="2026-07-16T11:30:00Z",
                                    window_end="2026-07-16T12:30:00Z"), DO)
    job = validate_success(res, 201)
    assert job["status"] == "SCHEDULED"


# ── Rule 8: resource_temporal_overlap / truck_closed_interval_aggregate_capacity ──

def test_truck_closed_window_touching_endpoints_rejected(api):
    """PRD §3.6: "across the same truck, sum the containers of all `SCHEDULED` or
    `IN_TRANSIT` move orders whose closed `[window_start, window_end]` windows intersect the
    new move's window; if adding this move's one container would push that sum above the
    truck's `max_concurrent_containers`, the move is rejected with
    `ERR_TRUCK_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/truck_closed_interval_aggregate_capacity
    """
    # Two ACTIVE C16 agreements share one truck (capacity 1); moves [09:00,11:00] and
    # [11:00,13:00] touch at 11:00 -> closed-interval intersection -> 2 > 1 -> rejected.
    world1, ag1, unit1 = F.setup_active_agreement(
        tier_code="NONE", inventory_total_units=2, with_truck=True)
    truck = world1["truck"]
    # Second agreement at the same depot drawing the second unit.
    ag2, unit2 = F.create_quoted_then_reserved(world1, agreement_overrides={"site_address": "B St"})
    job2 = validate_success(api.create_delivery_job(
        create_delivery_job_payload(ag2["id"], world1["crew"]["id"], unit2["id"],
                                    window_start="2026-07-16T13:00:00Z",
                                    window_end="2026-07-16T15:00:00Z"), DO), 201)
    validate_success(api.complete_delivery_job(job2["id"], DO), 200)

    F.schedule_move(world1, ag1, unit1, destination_state_code="CA", distance_miles=30,
                    window_start="2026-07-20T09:00:00Z", window_end="2026-07-20T11:00:00Z")

    res = api.create_move_order({
        "agreement_id": ag2["id"], "truck_id": truck["id"], "container_unit_id": unit2["id"],
        "origin_depot_id": world1["depot"]["id"], "destination_state_code": "CA",
        "distance_miles": 40, "window_start": "2026-07-20T11:00:00Z",
        "window_end": "2026-07-20T13:00:00Z"}, DO)
    validate_error(res, "ERR_TRUCK_CAPACITY_EXCEEDED")


def test_truck_capacity_within_limit_allows_overlap(api):
    """PRD §3.6: "if adding this move's one container would push that sum above the truck's
    `max_concurrent_containers`, the move is rejected with `ERR_TRUCK_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/truck_closed_interval_aggregate_capacity
    """
    # Same touching windows but a capacity-2 truck: 2 containers does not exceed 2, so allowed.
    world1, ag1, unit1 = F.setup_active_agreement(
        tier_code="NONE", inventory_total_units=2, with_truck=True)
    # Re-create a higher-capacity truck at the same depot.
    truck = F.create_truck(world1["depot"]["id"], plate="TRK-CAP2", max_concurrent_containers=2)
    ag2, unit2 = F.create_quoted_then_reserved(world1, agreement_overrides={"site_address": "B St"})
    job2 = validate_success(api.create_delivery_job(
        create_delivery_job_payload(ag2["id"], world1["crew"]["id"], unit2["id"],
                                    window_start="2026-07-16T13:00:00Z",
                                    window_end="2026-07-16T15:00:00Z"), DO), 201)
    validate_success(api.complete_delivery_job(job2["id"], DO), 200)

    validate_success(api.create_move_order({
        "agreement_id": ag1["id"], "truck_id": truck["id"], "container_unit_id": unit1["id"],
        "origin_depot_id": world1["depot"]["id"], "destination_state_code": "CA",
        "distance_miles": 30, "window_start": "2026-07-20T09:00:00Z",
        "window_end": "2026-07-20T11:00:00Z"}, DO), 201)

    res = api.create_move_order({
        "agreement_id": ag2["id"], "truck_id": truck["id"], "container_unit_id": unit2["id"],
        "origin_depot_id": world1["depot"]["id"], "destination_state_code": "CA",
        "distance_miles": 40, "window_start": "2026-07-20T11:00:00Z",
        "window_end": "2026-07-20T13:00:00Z"}, DO)
    move2 = validate_success(res, 201)
    assert move2["status"] == "SCHEDULED"


# ── Rule 9: compensating_invariant / inventory_conservation_reserve_then_cancel ──

def test_reserve_decrements_available_increments_reserved(api):
    """PRD §2.6: "The `available_units` count is `total_units` minus `reserved_units` minus
    `committed_units`." PRD §3.2: "increments the row's `reserved_units` by 1, recomputes
    `available_units`".

    Design: Difficulty/compensating_invariant/inventory_conservation_reserve_then_cancel
    """
    world = F.seed_world(size_code="C16", with_crew=False, inventory_total_units=1,
                         customer_email="inv@x.com")
    ag, unit = F.create_quoted_then_reserved(world)
    inv = validate_success(api.get_depot_inventory(world["inventory"]["id"], DO), 200)
    assert inv["available_units"] == 0
    assert inv["reserved_units"] == 1


def test_cancel_after_reserve_restores_pool(api):
    """PRD §2.6: "A reserve that is later cancelled restores the pool to exactly its
    pre-reserve count". PRD §3.2: "the reserved `ContainerUnit` flips to `RELEASED`, the
    inventory row's `reserved_units` is decremented by 1, and `available_units` is
    recomputed — restoring the pool to exactly the count it held before the reserve."

    Design: Difficulty/compensating_invariant/inventory_conservation_reserve_then_cancel
    """
    world = F.seed_world(size_code="C16", with_crew=False, inventory_total_units=1,
                         customer_email="inv2@x.com")
    ag, unit = F.create_quoted_then_reserved(world)
    validate_success(api.cancel_agreement(ag["id"], make_customer_headers(world["customer"]["id"])), 200)

    inv = validate_success(api.get_depot_inventory(world["inventory"]["id"], DO), 200)
    assert inv["available_units"] == 1
    assert inv["reserved_units"] == 0
    assert inv["committed_units"] == 0
    assert inv["total_units"] == inv["available_units"] + inv["reserved_units"] + inv["committed_units"]


# ── Rule 9: compensating_invariant / ledger_conservation_move_schedule_then_cancel ──

def test_move_schedule_raises_final_balance(api):
    """PRD §3.8: "Under the final variant — used while `lifecycle_status` is `CLOSING` or
    `CLOSED` — every posted debit is counted, including `MOVE` and `LATE_FEE`; the final
    balance therefore exceeds the provisional balance by exactly the sum of the `MOVE` and
    `LATE_FEE` debits."

    Design: Difficulty/compensating_invariant/ledger_conservation_move_schedule_then_cancel
    """
    # PLUS C16 provisional 24671; LOCAL 30mi move posts MOVE 8900+350*30=19400.
    # The move is dispatched + completed (unit returns ON_SITE, MOVE charge stays) so
    # request-closeout is not blocked by open logistics (PRD §3.5). Once CLOSING, the
    # FINAL variant counts the MOVE debit: balance = 24671 + 19400 = 44071.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000},
        with_truck=True)
    cust_id = world["customer"]["id"]
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30)
    F.dispatch_and_complete_move(move)
    F.request_closeout(ag, cust_id)
    with_move = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert with_move["balance_due_cents"] == 44071


def test_move_cancel_adjustment_restores_final_balance(api):
    """PRD §3.6: "if a `MOVE` charge was posted at scheduling, the system posts a
    compensating `ADJUSTMENT` charge equal to the negative of `quoted_cost_cents` and
    recomputes `balance_due_cents`, so the ledger nets back to where it stood before the
    move."

    Design: Difficulty/compensating_invariant/ledger_conservation_move_schedule_then_cancel
    """
    # Cancel the move while the agreement is still ACTIVE (the move is SCHEDULED, the only
    # state in which cancel is allowed). Cancellation posts the compensating ADJUSTMENT
    # (-19400). With no open logistics remaining, request-closeout then succeeds (PRD §3.5),
    # and the FINAL variant counts both the MOVE (+19400) and the ADJUSTMENT (-19400),
    # netting back to the pre-move balance of 24671.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000},
        with_truck=True)
    cust_id = world["customer"]["id"]
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30)
    validate_success(api.cancel_move_order(move["id"], DO), 200)
    F.request_closeout(ag, cust_id)

    after = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert after["balance_due_cents"] == 24671
