"""Slot commit gating: production-day capacity boundaries, peak-ratio flooring,
route-window overlap, and the slot-commit OCC guard."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_customer_headers,
    make_dispatcher_headers,
    commit_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check — admit exactly at effective cap
# ---------------------------------------------------------------------------
def test_commit_admitted_exactly_at_effective_capacity(api):
    """PRD 3.11: "A reservation of the order's units is admissible exactly when the
    day's `units_committed` plus those units is at or below the effective capacity
    - landing exactly on the effective capacity is admissible, while exceeding it
    by even one unit is not."

    Non-peak cap=2 already at units_committed=1; a second single-unit commit lands
    exactly on 2 and is admitted (COMMITTED).

    Design: Difficulty/boundary_precision_check/capacity_admits_exactly_at_effective_cap
    """
    # First order takes one unit on a cap-2 day.
    first_order, customer, first_res, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 2})
    customer_headers = make_customer_headers(customer["id"])
    pday_mid = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_mid["units_committed"] == 1, pday_mid

    # Boundary order: 1 unit, reusing the same product/pday/customer.
    boundary = fx.create_order(customer, product, pday)
    fx.add_line(boundary, customer, units=1)
    fx.quote(boundary, customer)
    fx.pay_deposit(boundary, customer)
    proof = fx.post_proof(boundary, "pf5")
    fx.approve_proof(boundary, proof, customer)
    fx.pay_balance(boundary, customer, 0)
    res = fx.create_slot(boundary, customer, "PICKUP")

    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(boundary["id"], customer_headers), 200)
    committed = validate_success(
        api.commit_slot(boundary["id"], res["id"], commit_payload(fresh["version"]), dispatcher), 200)
    assert committed["status"] == "COMMITTED", committed

    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 2, pday_after


def test_commit_rejected_one_unit_over_effective_capacity(api):
    """PRD 3.11: "A reservation of the order's units is admissible exactly when the
    day's `units_committed` plus those units is at or below the effective capacity
    - landing exactly on the effective capacity is admissible, while exceeding it
    by even one unit is not."

    Non-peak cap=2 already at units_committed=2 (full); a further single-unit
    commit (would make 3 == cap+1) is rejected with ERR_PRODUCTION_DAY_FULL.

    Design: Difficulty/boundary_precision_check/capacity_admits_exactly_at_effective_cap
    """
    first_order, customer, first_res, product, pday = fx.setup_committed_pickup_order(
        units=2, pday_overrides={"unit_capacity": 2})
    customer_headers = make_customer_headers(customer["id"])

    over = fx.create_order(customer, product, pday)
    fx.add_line(over, customer, units=1)
    fx.quote(over, customer)
    fx.pay_deposit(over, customer)
    proof = fx.post_proof(over, "over")
    fx.approve_proof(over, proof, customer)
    fx.pay_balance(over, customer, 0)
    res = fx.create_slot(over, customer, "PICKUP")
    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(over["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(over["id"], res["id"], commit_payload(fresh["version"]), dispatcher),
        ApiErrorId.ERR_PRODUCTION_DAY_FULL)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap — aggregate capacity tally
# ---------------------------------------------------------------------------
def test_commit_rejected_when_production_day_full(api):
    """PRD 3.11: "the production day must have room: committing must not push the
    day's `units_committed` plus this order's units over the day's effective
    capacity, or it is rejected with `ERR_PRODUCTION_DAY_FULL`."

    Non-peak cap=1 already fully committed; a second order's commit is rejected and
    units_committed stays 1.

    Design: Difficulty/resource_temporal_overlap/production_day_aggregate_capacity_overlap
    """
    first_order, customer, first_res, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 1})
    customer_headers = make_customer_headers(customer["id"])

    second = fx.create_order(customer, product, pday)
    fx.add_line(second, customer, units=1)
    fx.quote(second, customer)
    fx.pay_deposit(second, customer)
    proof = fx.post_proof(second, "p2")
    fx.approve_proof(second, proof, customer)
    fx.pay_balance(second, customer, 0)
    res = fx.create_slot(second, customer, "PICKUP")

    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(second["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(second["id"], res["id"], commit_payload(fresh["version"]), dispatcher),
        ApiErrorId.ERR_PRODUCTION_DAY_FULL)

    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 1, pday_after


def test_capacity_rejected_commit_leaves_reservation_held(api):
    """PRD 3.11: "the production day must have room: committing must not push the
    day's `units_committed` plus this order's units over the day's effective
    capacity, or it is rejected with `ERR_PRODUCTION_DAY_FULL`."
    PRD 3.11: "A successful commit moves the reservation from `HELD` to
    `COMMITTED`".

    When a commit is rejected for a full day, the reservation never leaves HELD.

    Design: Difficulty/resource_temporal_overlap/production_day_aggregate_capacity_overlap
    """
    first_order, customer, first_res, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 1})
    customer_headers = make_customer_headers(customer["id"])

    second = fx.create_order(customer, product, pday)
    fx.add_line(second, customer, units=1)
    fx.quote(second, customer)
    fx.pay_deposit(second, customer)
    proof = fx.post_proof(second, "held")
    fx.approve_proof(second, proof, customer)
    fx.pay_balance(second, customer, 0)
    res = fx.create_slot(second, customer, "PICKUP")
    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(second["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(second["id"], res["id"], commit_payload(fresh["version"]), dispatcher),
        ApiErrorId.ERR_PRODUCTION_DAY_FULL)
    slots, _meta = validate_paginated(api.list_slots(second["id"], customer_headers))
    assert any(s["id"] == res["id"] and s["status"] == "HELD" for s in slots), slots


# ---------------------------------------------------------------------------
# Queue B: calculations — peak ratio floored
# ---------------------------------------------------------------------------
def test_peak_capacity_floor_ratio_applied(api):
    """PRD 3.11: "On a peak day the bakery reserves a safety margin: the effective
    capacity is `unit_capacity` multiplied by 0.80 and floored to a whole number of
    units."
    PRD 3.11: "committing must not push the day's `units_committed` plus this
    order's units over the day's effective capacity, or it is rejected with
    `ERR_PRODUCTION_DAY_FULL`."

    Peak cap=10 -> effective floor(10*0.80)=8; with 8 committed a 1-unit commit
    (would make 9) is rejected and the tally stays 8.

    Design: Corner/calculations/peak_capacity_floor_ratio_applied
    """
    first_order, customer, first_res, product, pday = fx.setup_committed_pickup_order(
        units=8, pday_overrides={"unit_capacity": 10, "is_peak": True})
    customer_headers = make_customer_headers(customer["id"])
    pday_mid = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_mid["units_committed"] == 8, pday_mid

    second = fx.create_order(customer, product, pday)
    fx.add_line(second, customer, units=1)
    fx.quote(second, customer)
    fx.pay_deposit(second, customer)
    proof = fx.post_proof(second, "pb")
    fx.approve_proof(second, proof, customer)
    fx.pay_balance(second, customer, 0)
    res = fx.create_slot(second, customer, "PICKUP")

    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(second["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(second["id"], res["id"], commit_payload(fresh["version"]), dispatcher),
        ApiErrorId.ERR_PRODUCTION_DAY_FULL)

    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 8, pday_after


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap — half-open route window
# ---------------------------------------------------------------------------
def test_delivery_window_interior_overlap_rejected(api):
    """PRD 3.11: "windows are half-open intervals running from `window_start_min`
    for `stop_minutes` (that is, `[start, start + stop_minutes)`), so a new window
    that touches an existing one only at its closing edge does not overlap, while
    any genuine interior overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    stop_minutes=60: a committed window [600,660); a second commit at 630 (interior
    overlap, 630<660) is rejected and stays HELD.

    Design: Difficulty/resource_temporal_overlap/delivery_route_halfopen_window_overlap
    """
    route = fx.create_route(route_name="Route 1", service_date="2026-06-20", stop_minutes=60)
    # Note: setup_committed_delivery_order does its own catalog; build a single
    # shared catalog so both orders share the production day and route.
    ctx = fx.setup_catalog()
    customer = ctx["customer"]
    product = ctx["product"]
    pday = ctx["production_day"]
    customer_headers = make_customer_headers(customer["id"])
    dispatcher = make_dispatcher_headers()

    # Order A committed at window_start_min=600.
    order_a, res_a = _drive_to_held_delivery(api, customer, product, pday, route, window=600)
    fresh_a = validate_success(api.get_order(order_a["id"], customer_headers), 200)
    validate_success(
        api.commit_slot(order_a["id"], res_a["id"], commit_payload(fresh_a["version"]), dispatcher), 200)

    # Order B requests DELIVERY at 630 (interior overlap with [600,660)).
    order_b, res_b = _drive_to_held_delivery(api, customer, product, pday, route, window=630)
    fresh_b = validate_success(api.get_order(order_b["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(order_b["id"], res_b["id"], commit_payload(fresh_b["version"]), dispatcher),
        ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)

    slots_b, _meta = validate_paginated(api.list_slots(order_b["id"], customer_headers))
    assert any(s["id"] == res_b["id"] and s["status"] == "HELD" for s in slots_b), slots_b


def test_delivery_window_adjacent_at_closing_edge_admitted(api):
    """PRD 3.11: "windows are half-open intervals running from `window_start_min`
    for `stop_minutes` (that is, `[start, start + stop_minutes)`), so a new window
    that touches an existing one only at its closing edge does not overlap, while
    any genuine interior overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    stop_minutes=60: a committed window [600,660); a second commit at exactly 660
    touches only the closing edge and is admitted (COMMITTED), proving adjacency is
    allowed.

    Design: Difficulty/resource_temporal_overlap/delivery_route_halfopen_window_overlap
    """
    route = fx.create_route(route_name="Route Adj", service_date="2026-06-20", stop_minutes=60)
    ctx = fx.setup_catalog()
    customer = ctx["customer"]
    product = ctx["product"]
    pday = ctx["production_day"]
    customer_headers = make_customer_headers(customer["id"])
    dispatcher = make_dispatcher_headers()

    order_a, res_a = _drive_to_held_delivery(api, customer, product, pday, route, window=600)
    fresh_a = validate_success(api.get_order(order_a["id"], customer_headers), 200)
    validate_success(
        api.commit_slot(order_a["id"], res_a["id"], commit_payload(fresh_a["version"]), dispatcher), 200)

    order_b, res_b = _drive_to_held_delivery(api, customer, product, pday, route, window=660)
    fresh_b = validate_success(api.get_order(order_b["id"], customer_headers), 200)
    committed = validate_success(
        api.commit_slot(order_b["id"], res_b["id"], commit_payload(fresh_b["version"]), dispatcher), 200)
    assert committed["status"] == "COMMITTED", committed


def _drive_to_held_delivery(api, customer, product, pday, route, window):
    """Build an order on the shared catalog up to a HELD DELIVERY reservation.
    Returns (order, reservation)."""
    order = fx.create_order(customer, product, pday)
    fx.add_line(order, customer, units=1)
    fx.quote(order, customer)
    fx.pay_deposit(order, customer)
    proof = fx.post_proof(order, "pd")
    fx.approve_proof(order, proof, customer)
    fx.pay_balance(order, customer, 0)
    reservation = fx.create_slot(order, customer, "DELIVERY", route_id=route["id"], window_start_min=window)
    return order, reservation


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict — state beats capacity
# ---------------------------------------------------------------------------
def test_commit_on_quoted_order_returns_invalid_state_before_capacity(api):
    """PRD 2.10: "(6) that the target transition is legal from the current state
    (`ERR_INVALID_STATE`); (7) the optimistic-concurrency version check on the two
    guarded writes (`ERR_STALE_ORDER_VERSION`); and then the business rules ...
    production-day capacity ... as detailed in Section 3."
    PRD 3.11: "Commit is gated on several preconditions evaluated in order. The
    order must be in `PROOF_APPROVED`."

    A commit against a still-QUOTED order on a saturated day reports the
    higher-priority ERR_INVALID_STATE, not ERR_PRODUCTION_DAY_FULL.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_stale_commit
    """
    # Saturating order consumes the only unit on a cap-1 day.
    full_order, customer, full_res, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 1})
    customer_headers = make_customer_headers(customer["id"])
    dispatcher = make_dispatcher_headers()

    # Victim order: only QUOTED, with a HELD reservation, on the now-full day.
    victim = fx.create_order(customer, product, pday)
    fx.add_line(victim, customer, units=1)
    fx.quote(victim, customer)
    res_v = fx.create_slot(victim, customer, "PICKUP")
    fresh_v = validate_success(api.get_order(victim["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(victim["id"], res_v["id"], commit_payload(fresh_v["version"]), dispatcher),
        ApiErrorId.ERR_INVALID_STATE)


def test_invalid_state_commit_leaves_quoted_order_and_held_reservation(api):
    """PRD 3.11: "Commit is gated on several preconditions evaluated in order. The
    order must be in `PROOF_APPROVED`."
    PRD 3.11: "A successful commit moves the reservation from `HELD` to
    `COMMITTED`".

    The rejected commit against a QUOTED order leaves both the order's
    production_status QUOTED and the reservation HELD - no partial effect.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_stale_commit
    """
    full_order, customer, full_res, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 1})
    customer_headers = make_customer_headers(customer["id"])
    dispatcher = make_dispatcher_headers()

    victim = fx.create_order(customer, product, pday)
    fx.add_line(victim, customer, units=1)
    fx.quote(victim, customer)
    res_v = fx.create_slot(victim, customer, "PICKUP")
    fresh_v = validate_success(api.get_order(victim["id"], customer_headers), 200)
    validate_error(
        api.commit_slot(victim["id"], res_v["id"], commit_payload(fresh_v["version"]), dispatcher),
        ApiErrorId.ERR_INVALID_STATE)

    order_after = validate_success(api.get_order(victim["id"], customer_headers), 200)
    assert order_after["production_status"] == "QUOTED", order_after
    slots, _meta = validate_paginated(api.list_slots(victim["id"], customer_headers))
    assert any(s["id"] == res_v["id"] and s["status"] == "HELD" for s in slots), slots


# ---------------------------------------------------------------------------
# Queue B: rbac / cross_cutting — slot-commit OCC guard
# ---------------------------------------------------------------------------
def test_commit_with_stale_order_version_rejected(api):
    """PRD 2.7: "A commit request must carry `expected_order_version` holding the
    order `version` the dispatcher last read. If the order's `version` has advanced
    since then ... the commit is rejected with `ERR_STALE_ORDER_VERSION` (HTTP
    412)".

    A commit carrying a version one behind the order's true version is rejected.

    Design: Corner/rbac/dispatcher_cannot_commit_with_stale_order_version
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=1)
    customer_headers = make_customer_headers(customer["id"])
    reservation = fx.create_slot(order, customer, "PICKUP")
    dispatcher = make_dispatcher_headers()
    fresh = validate_success(api.get_order(order["id"], customer_headers), 200)
    stale_version = fresh["version"] - 1
    validate_error(
        api.commit_slot(order["id"], reservation["id"], commit_payload(stale_version), dispatcher),
        ApiErrorId.ERR_STALE_ORDER_VERSION)
