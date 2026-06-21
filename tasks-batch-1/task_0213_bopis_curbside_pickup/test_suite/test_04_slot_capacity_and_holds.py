"""Pickup slot capacity boundaries, hold-expiry temporal boundaries, and the
order↔slot cross-entity gate.

Difficulty queue A (boundary_precision_check, cross_entity_state_dependency slot,
resource_temporal_overlap slot).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


def _book_one(api, store_id, slot_id, product_id):
    """Create + submit one order from a fresh customer booking the slot.
    Returns the submitted order. Reads the current slot version itself."""
    customer = fx.create_customer()
    order = fx.create_draft_order(customer["id"], store_id)
    fx.add_line(order["id"], customer["id"], product_id, 1)
    slot_v = fx.get_slot_version(slot_id)
    return fx.submit_order(order["id"], customer["id"], slot_id, slot_v)


def test_slot_fill_boundary_open_at_capacity_minus_one_full_at_capacity(api):
    """PRD §2.7: "When `booked_count` is one below capacity the slot is still `OPEN`
    (one space left); when `booked_count` equals capacity the slot is `FULL` and further
    booking is refused."
    PRD §3.3: "the slot is `OPEN`, meaning `booked_count` is strictly less than
    `capacity` (otherwise `ERR_SLOT_FULL`)"

    Design: Difficulty/boundary_precision_check/slot_fill_capacity_boundary_open_vs_full
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=2)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]

    _book_one(api, store_id, slot_id, product_id)  # booked_count 0 -> 1, still OPEN
    after_first = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert after_first["booked_count"] == 1 and after_first["fill_status"] == "OPEN", after_first

    _book_one(api, store_id, slot_id, product_id)  # booked_count 1 -> 2 (cap-1 -> cap)
    after_second = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert after_second["booked_count"] == 2 and after_second["fill_status"] == "FULL", after_second


def test_slot_third_booking_at_capacity_rejected_slot_full(api):
    """PRD §3.3: "the slot is `OPEN`, meaning `booked_count` is strictly less than
    `capacity` (otherwise `ERR_SLOT_FULL`)"

    Design: Difficulty/boundary_precision_check/slot_fill_capacity_boundary_open_vs_full
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=2)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    _book_one(api, store_id, slot_id, product_id)
    _book_one(api, store_id, slot_id, product_id)
    # third order: booked_count == capacity == 2 -> rejected
    customer3 = fx.create_customer()
    order3 = fx.create_draft_order(customer3["id"], store_id)
    fx.add_line(order3["id"], customer3["id"], product_id, 1)
    slot_v = fx.get_slot_version(slot_id)
    resp = api.submit_order(order3["id"],
                            f.submit_order_payload(slot_id, slot_v),
                            make_customer_headers(customer3["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value)


def test_hold_expire_rejected_one_minute_before_deadline(api):
    """PRD §2.8: "A hold is eligible to expire only while the clock is at or after
    `expires_at` — the comparison is inclusive at the deadline. Precisely: at the
    instant the clock equals `expires_at`, the hold is expirable; one minute earlier,
    it is not."
    PRD §3.7: "if the clock has not yet reached the hold's `expires_at`, that request is
    rejected with `ERR_HOLD_NOT_EXPIRABLE`."

    Design: Difficulty/boundary_precision_check/hold_expiry_deadline_inclusive_boundary
    """
    # staged_at 10:00, hold_window 120 -> expires_at 12:00.
    setup = fx.raise_customer_to_strikes(0, hold_window_minutes=120)
    customer, store, product, slot = setup["customer"], setup["store"], setup["product"], setup["slot"]
    fx.set_clock("2026-06-05T10:00:00Z")
    slot_v = fx.get_slot_version(slot["id"])
    order = fx.create_draft_order(customer["id"], store["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    fx.submit_order(order["id"], customer["id"], slot["id"], slot_v)
    fx.start_picking(order["id"])
    fx.pick_line(line["id"], 1)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])

    fx.set_clock("2026-06-05T11:59:00Z")
    resp = api.expire_order(order["id"], make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_EXPIRABLE.value)


def test_hold_expire_succeeds_at_exact_deadline(api):
    """PRD §2.8: "at the instant the clock equals `expires_at`, the hold is expirable"
    PRD §3.7: "Expiry transitions the order's `fulfillment_status` from
    `AWAITING_PICKUP` to `EXPIRED`"

    Design: Difficulty/boundary_precision_check/hold_expiry_deadline_inclusive_boundary
    """
    setup = fx.raise_customer_to_strikes(0, hold_window_minutes=120)
    customer, store, product, slot = setup["customer"], setup["store"], setup["product"], setup["slot"]
    fx.set_clock("2026-06-05T10:00:00Z")
    slot_v = fx.get_slot_version(slot["id"])
    order = fx.create_draft_order(customer["id"], store["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    fx.submit_order(order["id"], customer["id"], slot["id"], slot_v)
    fx.start_picking(order["id"])
    fx.pick_line(line["id"], 1)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])

    fx.set_clock("2026-06-05T12:00:00Z")  # == expires_at
    expired = validate_success(api.expire_order(order["id"], make_manager_headers()))
    assert expired["fulfillment_status"] == "EXPIRED", expired


def test_order_submit_blocked_when_slot_full(api):
    """PRD §3.3: "the slot is `OPEN`, meaning `booked_count` is strictly less than
    `capacity` (otherwise `ERR_SLOT_FULL`)"

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_slot_open
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=1)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    _book_one(api, store_id, slot_id, product_id)  # slot -> FULL

    slot_state = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert slot_state["fill_status"] == "FULL", slot_state

    customer2 = fx.create_customer()
    order2 = fx.create_draft_order(customer2["id"], store_id)
    fx.add_line(order2["id"], customer2["id"], product_id, 1)
    slot_v = fx.get_slot_version(slot_id)
    resp = api.submit_order(order2["id"], f.submit_order_payload(slot_id, slot_v),
                            make_customer_headers(customer2["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value)


def test_order_submit_succeeds_against_open_slot(api):
    """PRD §2.7: "Booking is permitted only while the slot is `OPEN` — that is, while
    `booked_count` is strictly less than `capacity`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_slot_open
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=2)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], store_id)
    fx.add_line(order["id"], customer["id"], product_id, 1)
    submitted = validate_success(api.submit_order(
        order["id"], f.submit_order_payload(slot_id, base["slot_version"]),
        make_customer_headers(customer["id"])))
    assert submitted["fulfillment_status"] == "SUBMITTED", submitted


def test_slot_aggregate_capacity_consumed_over_fixed_window(api):
    """PRD §2.7: "It carries a `capacity` (the maximum number of orders that may book
    it, which must be greater than zero)"
    PRD §3.3: "the slot is `OPEN`, meaning `booked_count` is strictly less than
    `capacity` (otherwise `ERR_SLOT_FULL`)"

    Design: Difficulty/resource_temporal_overlap/pickup_slot_aggregate_capacity_window_overlap
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=1,
                                 window_start="2026-06-02T10:00:00Z",
                                 window_end="2026-06-02T11:00:00Z")
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    _book_one(api, store_id, slot_id, product_id)  # capacity 1 consumed

    customer2 = fx.create_customer()
    order2 = fx.create_draft_order(customer2["id"], store_id)
    fx.add_line(order2["id"], customer2["id"], product_id, 1)
    slot_v = fx.get_slot_version(slot_id)
    resp = api.submit_order(order2["id"], f.submit_order_payload(slot_id, slot_v),
                            make_customer_headers(customer2["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value)

    slot_state = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert slot_state["booked_count"] == 1 == slot_state["capacity"], slot_state


def test_slot_window_capacity_one_second_booking_collides(api):
    """PRD §2.7: "The derived `fill_status` is `FULL` when `booked_count` is greater
    than or equal to `capacity`, and `OPEN` otherwise"

    Design: Difficulty/resource_temporal_overlap/pickup_slot_aggregate_capacity_window_overlap
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=1,
                                 window_start="2026-06-02T10:00:00Z",
                                 window_end="2026-06-02T11:00:00Z")
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    _book_one(api, store_id, slot_id, product_id)
    full = validate_success(api.get_pickup_slot(slot_id, make_manager_headers()))
    assert full["fill_status"] == "FULL"
