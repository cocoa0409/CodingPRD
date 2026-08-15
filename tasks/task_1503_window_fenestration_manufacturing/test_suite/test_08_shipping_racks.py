"""Shipping racks, reservations, occupancy buffers, and loading (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    assign_order,
    confirm_order,
    create_draft_order,
    create_open_wave,
    create_rack,
    create_reservation,
    get_success_data,
    list_line_units,
    lock_and_release,
    produce_line,
    setup_confirmed_order,
    setup_mn_catalog,
    setup_order_in_production,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PL = TEST_USERS["production_lead_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]


def _produce_line(api, line_id, argon=95):
    produce_line(line_id, argon)


def test_rack_occupancy_buffer_day_conflicts(api):
    """PRD §3.6: "Put concretely, a `load_date` exactly one day after a prior
    `ship_date` still conflicts — the turnover day is unavailable — while two
    days after is allowed; same-day turnover is never allowed."
    PRD §3.6: "A colliding request is rejected with
    `ERR_RACK_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rack_occupancy_buffer_semantics
    """
    env = setup_order_in_production(quantity=1)
    rack = create_rack(rack_code="R5")
    create_reservation(rack["id"], env["order"]["id"],
                       load_date="2026-09-10T00:00:00Z", ship_date="2026-09-20T00:00:00Z")

    clash = api.create_rack_reservation(
        rack["id"],
        {"order_id": env["order"]["id"],
         "load_date": "2026-09-21T00:00:00Z", "ship_date": "2026-09-25T00:00:00Z"},
        SC,
    )
    validate_error(clash, ApiErrorId.ERR_RACK_OCCUPANCY_CONFLICT, expected_status=409)


def test_rack_occupancy_two_days_after_allowed(api):
    """PRD §3.6: "Put concretely, a `load_date` exactly one day after a prior
    `ship_date` still conflicts — the turnover day is unavailable — while two
    days after is allowed; same-day turnover is never allowed."
    PRD §3.6: "The rack's `status` is never set directly: it is `BOOKED` while
    at least one active reservation (status `RESERVED` or `LOADING`) exists and
    `AVAILABLE` otherwise, flipping automatically as reservations come and go."

    Design: Difficulty/resource_temporal_overlap/rack_occupancy_buffer_semantics
    """
    env = setup_order_in_production(quantity=1)
    rack = create_rack(rack_code="R5")
    create_reservation(rack["id"], env["order"]["id"],
                       load_date="2026-09-10T00:00:00Z", ship_date="2026-09-20T00:00:00Z")

    accepted = api.create_rack_reservation(
        rack["id"],
        {"order_id": env["order"]["id"],
         "load_date": "2026-09-22T00:00:00Z", "ship_date": "2026-09-25T00:00:00Z"},
        SC,
    )
    reservation = validate_success(accepted, 201)
    assert reservation["status"] == "RESERVED"

    rack_after = get_success_data(api.get_rack(rack["id"], SC))
    assert rack_after["status"] == "BOOKED", (
        "two active reservations coexist under the closed-interval + buffer rule"
    )


def test_reservation_cancel_frees_occupancy_window(api):
    """PRD §3.6: "A reservation can instead be cancelled, but only before
    anything has been loaded — `assigned_units` must still be zero
    (`ERR_INVALID_STATE`) — moving `RESERVED → CANCELLED` and again recomputing
    the rack's status, which returns to `AVAILABLE` when no active reservations
    remain."
    PRD §3.6: "Occupancy is a closed interval with a one-day turnover buffer: a
    new window conflicts with an existing active reservation on the same rack
    unless the new `load_date` falls at least two calendar days after the
    existing reservation's `ship_date`, or the existing reservation's
    `load_date` falls at least two calendar days after the new `ship_date`."

    Design: Corner/state_machines/reservation_cancel_frees_occupancy_window
    """
    env = setup_order_in_production(quantity=1)
    rack = create_rack(rack_code="R2")
    res1 = create_reservation(rack["id"], env["order"]["id"],
                              load_date="2026-09-10T00:00:00Z",
                              ship_date="2026-09-20T00:00:00Z")

    cancelled = validate_success(api.cancel_rack_reservation(res1["id"], SC), 200)
    assert cancelled["status"] == "CANCELLED"
    rack_mid = get_success_data(api.get_rack(rack["id"], SC))
    assert rack_mid["status"] == "AVAILABLE"

    # the CANCELLED reservation drops out of the overlap set entirely
    res2 = validate_success(api.create_rack_reservation(
        rack["id"],
        {"order_id": env["order"]["id"],
         "load_date": "2026-09-10T00:00:00Z", "ship_date": "2026-09-20T00:00:00Z"},
        SC,
    ), 201)
    assert res2["status"] == "RESERVED"


def test_rack_slot_loads_up_to_capacity_admitted(api):
    """PRD §3.6: "the line must be `COMPLETED` (`ERR_INVALID_STATE`), must
    belong to the reservation's order (`ERR_RACK_WRONG_ORDER`), must not already
    be loaded — a line whose `rack_id` is already set is rejected with
    `ERR_INVALID_STATE` — and the load must fit: the line's `quantity` added to
    `assigned_units` may not exceed the rack's `slot_capacity`, with equality
    allowed (`ERR_RACK_CAPACITY_EXCEEDED`)"

    Design: Difficulty/boundary_precision_check/rack_slot_equality_boundary
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line3 = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=3)
    line1a = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    line1b = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order["id"])
    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=2000)
    assign_order(wave["id"], order["id"])
    lock_and_release(wave["id"])
    _produce_line(api, line3["id"])
    _produce_line(api, line1a["id"])
    _produce_line(api, line1b["id"])

    rack = create_rack(rack_code="R9", slot_capacity=4)
    reservation = create_reservation(rack["id"], order["id"])

    first = validate_success(api.load_rack_reservation(
        reservation["id"], {"order_line_id": line3["id"]}, SC), 200)
    assert first["assigned_units"] == 3
    second = validate_success(api.load_rack_reservation(
        reservation["id"], {"order_line_id": line1a["id"]}, SC), 200)
    assert second["assigned_units"] == 4, "equality with slot_capacity is admitted"


def test_rack_slot_beyond_capacity_rejected(api):
    """PRD §3.6: "the load must fit: the line's `quantity` added to
    `assigned_units` may not exceed the rack's `slot_capacity`, with equality
    allowed (`ERR_RACK_CAPACITY_EXCEEDED`)"

    Design: Difficulty/boundary_precision_check/rack_slot_equality_boundary
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line3 = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=3)
    line1a = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    line1b = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order["id"])
    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=2000)
    assign_order(wave["id"], order["id"])
    lock_and_release(wave["id"])
    _produce_line(api, line3["id"])
    _produce_line(api, line1a["id"])
    _produce_line(api, line1b["id"])

    rack = create_rack(rack_code="R9", slot_capacity=4)
    reservation = create_reservation(rack["id"], order["id"])
    validate_success(api.load_rack_reservation(
        reservation["id"], {"order_line_id": line3["id"]}, SC), 200)
    validate_success(api.load_rack_reservation(
        reservation["id"], {"order_line_id": line1a["id"]}, SC), 200)

    third = api.load_rack_reservation(
        reservation["id"], {"order_line_id": line1b["id"]}, SC)
    validate_error(third, ApiErrorId.ERR_RACK_CAPACITY_EXCEEDED, expected_status=409)

    line_after = validate_success(api.get_order_line(line1b["id"], SC), 200)
    assert line_after["rack_id"] is None


def test_ship_rack_before_order_completed_returns_error(api):
    """PRD §3.6: "Shipping a reservation requires the order's
    `production_status` to be `COMPLETED`; shipping against an order in any
    other state is rejected with `ERR_ORDER_NOT_SHIPPABLE`."

    Design: Corner/state_machines/ship_rack_before_order_completed_returns_error
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line1 = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order["id"])
    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=500)
    assign_order(wave["id"], order["id"])
    lock_and_release(wave["id"])
    _produce_line(api, line1["id"])  # line2 stays IN_PRODUCTION -> order IN_PROGRESS

    rack = create_rack(rack_code="R3")
    reservation = create_reservation(rack["id"], order["id"])
    validate_success(api.load_rack_reservation(
        reservation["id"], {"order_line_id": line1["id"]}, SC), 200)

    res = api.ship_rack_reservation(reservation["id"], SC)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_SHIPPABLE, expected_status=409)
    after = validate_success(api.get_rack_reservation(reservation["id"], SC), 200)
    assert after["status"] == "LOADING"


def test_rack_load_wrong_order_returns_error(api):
    """PRD §3.6: "the line must be `COMPLETED` (`ERR_INVALID_STATE`), must
    belong to the reservation's order (`ERR_RACK_WRONG_ORDER`), must not already
    be loaded — a line whose `rack_id` is already set is rejected with
    `ERR_INVALID_STATE` — and the load must fit"

    Design: Corner/endpoints/rack_load_wrong_order_returns_error
    """
    cat = setup_mn_catalog()
    order_a = create_draft_order(cat["dealer"]["id"])
    line_a = add_line(order_a["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_a["id"])
    order_b = create_draft_order(cat["dealer"]["id"])
    line_b = add_line(order_b["id"], cat["series"]["id"], cat["glass"]["id"], quantity=1)
    confirm_order(order_b["id"])

    wave = create_open_wave(capacity_units=10, capacity_glass_sqft=500)
    assign_order(wave["id"], order_a["id"])
    assign_order(wave["id"], order_b["id"])
    lock_and_release(wave["id"])
    _produce_line(api, line_a["id"])
    _produce_line(api, line_b["id"])

    rack = create_rack(rack_code="R4")
    reservation = create_reservation(rack["id"], order_a["id"])
    res = api.load_rack_reservation(reservation["id"], {"order_line_id": line_b["id"]}, SC)
    validate_error(res, ApiErrorId.ERR_RACK_WRONG_ORDER, expected_status=409)

    after = validate_success(api.get_rack_reservation(reservation["id"], SC), 200)
    assert after["status"] == "RESERVED"
    assert after["assigned_units"] == 0


def test_rack_reservation_requires_order_in_production(api):
    """PRD §3.6: "Reserving a rack takes the `order_id`, a `load_date`, and a
    `ship_date`. The order must be `IN_PROGRESS` or `COMPLETED`."
    PRD §2.10: "Any transition attempted from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE` unless a more specific state error
    applies."

    Design: Difficulty/cross_entity_state_dependency/rack_reservation_requires_order_in_production
    """
    env = setup_confirmed_order()
    rack = create_rack()
    res = api.create_rack_reservation(
        rack["id"],
        {"order_id": env["order"]["id"],
         "load_date": "2026-09-02T00:00:00Z", "ship_date": "2026-09-05T00:00:00Z"},
        SC,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_rejected_reservation_leaves_rack_available(api):
    """PRD §3.6: "The rack's `status` is never set directly: it is `BOOKED`
    while at least one active reservation (status `RESERVED` or `LOADING`)
    exists and `AVAILABLE` otherwise, flipping automatically as reservations
    come and go."

    Design: Difficulty/cross_entity_state_dependency/rack_reservation_requires_order_in_production
    """
    env = setup_confirmed_order()
    rack = create_rack()
    validate_error(api.create_rack_reservation(
        rack["id"],
        {"order_id": env["order"]["id"],
         "load_date": "2026-09-02T00:00:00Z", "ship_date": "2026-09-05T00:00:00Z"},
        SC,
    ), ApiErrorId.ERR_INVALID_STATE)
    rack_after = get_success_data(api.get_rack(rack["id"], SC))
    assert rack_after["status"] == "AVAILABLE"
