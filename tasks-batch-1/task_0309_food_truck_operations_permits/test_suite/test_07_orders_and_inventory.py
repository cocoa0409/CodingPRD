"""POS orders: the parallel lifecycle x payment dimensions, the empty-order boundary, prepared-
unit conservation, and the order/payment precondition gates.

Queue A: non_linear_state_machine/order_parallel_lifecycle_x_payment_dimensions,
         boundary_precision_check/settle_empty_order_zero_lines_rejected,
         cross_entity_state_dependency/open_order_requires_booking_arrived,
         compensating_invariant/prepared_units_conserved_void_never_consumes.
Queue B: order_discount_code_defaults_none, create_order_line_bad_quantity_zero...,
         depart_with_open_order_blocked, capture_before_authorize..., settle_before_capture...,
         insufficient_prepared_units_blocks_settle, discard_below_consumed_rejected,
         add_unlisted_menu_item_to_order_rejected.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_arrived_booking, setup_captured_order, setup_reserved_booking,
    make_operable_truck, add_menu_item, add_prep_batch,
    open_order, add_line, authorize, capture, settle,
    api_client, TEST_USERS, make_operator_truck_headers,
    create_order_payload, create_order_line_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── non_linear_state_machine / order parallel dimensions ───────────────────

def test_void_captured_order_voids_and_refunds(api):
    """PRD §3.7: "Voiding an order is the alternative lifecycle exit, the transition
    OPEN -> VOID ... If the order's payment_status was CAPTURED at the time of the void, the
    payment dimension independently transitions CAPTURED -> REFUNDED."

    A single void on an OPEN+CAPTURED order moves lifecycle_status to VOID and payment_status to
    REFUNDED — the two parallel dimensions evolving on one row.

    Design: Difficulty/non_linear_state_machine/order_parallel_lifecycle_x_payment_dimensions
    """
    ctx = setup_captured_order(
        "2026-06-05", clock_iso="2026-06-05T18:00:00.000Z",
        line_specs=[1], item_price_cents=300, prepared_units=10)
    h = make_operator_truck_headers(ctx["truck"]["id"])
    voided = validate_success(api.void_order(ctx["order"]["id"], h), 200)
    assert voided["lifecycle_status"] == "VOID"
    assert voided["payment_status"] == "REFUNDED"


def test_captured_order_dimensions_independent_before_void(api):
    """PRD §3.6: "An order carries two independent status dimensions: a lifecycle_status (OPEN,
    then either SETTLED or VOID) and a payment_status (UNPAID, AUTHORIZED, CAPTURED, and a
    terminal REFUNDED). They advance on separate triggers."

    After capture the order sits at lifecycle_status OPEN with payment_status CAPTURED — the two
    dimensions hold independent values on the same row.

    Design: Difficulty/non_linear_state_machine/order_parallel_lifecycle_x_payment_dimensions
    """
    ctx = setup_captured_order(
        "2026-07-25", clock_iso="2026-07-25T18:00:00.000Z",
        line_specs=[1], item_price_cents=300, prepared_units=10)
    assert ctx["order"]["lifecycle_status"] == "OPEN"
    assert ctx["order"]["payment_status"] == "CAPTURED"


# ─── boundary_precision_check / empty order (line count == 0) ───────────────

def test_authorize_empty_order_rejected(api):
    """PRD §3.6: "Authorizing a payment is the transition UNPAID -> AUTHORIZED; it requires the
    order to be OPEN (else ERR_ORDER_NOT_OPEN), the payment_status to currently be UNPAID (else
    ERR_PAYMENT_NOT_UNPAID), and the order to have at least one order line (else
    ERR_EMPTY_ORDER)."

    Authorizing an order with zero order lines is rejected with ERR_EMPTY_ORDER.

    Design: Difficulty/boundary_precision_check/settle_empty_order_zero_lines_rejected
    """
    ctx = setup_arrived_booking("2026-06-12", clock_iso="2026-06-12T18:00:00.000Z")
    order = open_order(ctx["truck"]["id"], ctx["booking"]["id"])
    h = make_operator_truck_headers(ctx["truck"]["id"])
    res = api.authorize_payment(order["id"], h)
    validate_error(res, "ERR_EMPTY_ORDER")


def test_authorize_single_line_order_succeeds(api):
    """PRD §3.6: "it requires ... the order to have at least one order line (else
    ERR_EMPTY_ORDER)."

    The X+1 side of the line-count boundary: an order with exactly one line authorizes
    successfully, moving payment_status to AUTHORIZED.

    Design: Difficulty/boundary_precision_check/settle_empty_order_zero_lines_rejected
    """
    ctx = setup_arrived_booking("2026-07-26", clock_iso="2026-07-26T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=10)
    add_prep_batch(truck_id, item["id"], units_made=10)
    order = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order["id"], item["id"], 1)
    h = make_operator_truck_headers(truck_id)
    authorized = validate_success(api.authorize_payment(order["id"], h), 200)
    assert authorized["payment_status"] == "AUTHORIZED"


# ─── cross_entity_state_dependency / open order requires booking ARRIVED ────

def test_open_order_requires_booking_arrived(api):
    """PRD §3.6: "Opening an order requires the owning truck to be OPERABLE (else
    ERR_TRUCK_NOT_OPERABLE) and the parent booking to be ARRIVED (else ERR_BOOKING_NOT_ARRIVED)."

    Opening an order against a still-RESERVED (not yet arrived) booking is rejected with
    ERR_BOOKING_NOT_ARRIVED, even on an OPERABLE truck.

    Design: Difficulty/cross_entity_state_dependency/open_order_requires_booking_arrived
    """
    ctx = setup_reserved_booking("2026-06-14", clock_iso="2026-06-14T18:00:00.000Z")
    h = make_operator_truck_headers(ctx["truck"]["id"])
    res = api.create_order(create_order_payload(ctx["booking"]["id"]), h)
    validate_error(res, "ERR_BOOKING_NOT_ARRIVED")


def test_open_order_succeeds_on_arrived_booking(api):
    """PRD §3.6: "A new order opens with `lifecycle_status` of `OPEN`, `payment_status` of
    `UNPAID`, and `live_total_cents` of 0."

    The positive side: against an ARRIVED booking the order opens OPEN/UNPAID.

    Design: Difficulty/cross_entity_state_dependency/open_order_requires_booking_arrived
    """
    ctx = setup_arrived_booking("2026-07-27", clock_iso="2026-07-27T18:00:00.000Z")
    h = make_operator_truck_headers(ctx["truck"]["id"])
    order = validate_success(api.create_order(create_order_payload(ctx["booking"]["id"]), h), 201)
    assert order["lifecycle_status"] == "OPEN"
    assert order["payment_status"] == "UNPAID"
    assert order["live_total_cents"] == 0


# ─── compensating_invariant / prepared units conserved (void never consumes) ─

def test_prepared_units_conserved_void_never_consumes(api):
    """PRD §3.5: "Open and void orders never consume prepared units — only settlement consumes."
    PRD §3.7: "A void never consumes prepared units — voided orders never deplete par."

    With prepared_units 10, settling one order of qty 2 consumes 2 (leaving 8); voiding a second
    order of qty 2 consumes nothing, so prepared_units stays 8.

    Design: Difficulty/compensating_invariant/prepared_units_conserved_void_never_consumes
    """
    ctx = setup_arrived_booking("2026-06-18", clock_iso="2026-06-18T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=10)
    add_prep_batch(truck_id, item["id"], units_made=10)
    # Order 1: settle (consumes 2).
    order1 = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order1["id"], item["id"], 2)
    authorize(truck_id, order1["id"])
    capture(truck_id, order1["id"])
    settle(truck_id, order1["id"], discount_code="NONE")
    # Order 2: void (consumes nothing).
    order2 = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order2["id"], item["id"], 2)
    authorize(truck_id, order2["id"])
    capture(truck_id, order2["id"])
    h = make_operator_truck_headers(truck_id)
    validate_success(api.void_order(order2["id"], h), 200)
    fresh = validate_success(api.get_menu_item(item["id"], DISPATCHER), 200)
    assert fresh["prepared_units"] == 8


def test_settle_consumes_prepared_units(api):
    """PRD §3.7: "On a successful settle ... each order line permanently consumes `prepared_units`
    of its menu item."

    Settling one order of qty 2 against prepared_units 10 consumes exactly 2 (leaving 8) — the
    settle-side of the conservation ledger that the void leaves intact.

    Design: Difficulty/compensating_invariant/prepared_units_conserved_void_never_consumes
    """
    ctx = setup_arrived_booking("2026-07-28", clock_iso="2026-07-28T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=10)
    add_prep_batch(truck_id, item["id"], units_made=10)
    order = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order["id"], item["id"], 2)
    authorize(truck_id, order["id"])
    capture(truck_id, order["id"])
    settle(truck_id, order["id"], discount_code="NONE")
    fresh = validate_success(api.get_menu_item(item["id"], DISPATCHER), 200)
    assert fresh["prepared_units"] == 8


# ─── Corner: order defaults, line constraints, payment preconditions ────────

def test_order_discount_code_defaults_none(api):
    """PRD §3.7: "Settlement accepts an optional `discount_code`, which is one of `NONE`,
    `HAPPY_HOUR`, or `BULK10` and defaults to `NONE`."
    PRD §3.6: "A new order opens with `lifecycle_status` of `OPEN`, `payment_status` of `UNPAID`,
    and `live_total_cents` of 0."

    An order created without a discount_code carries discount_code NONE and tip_cents 0.

    Design: Corner/entities/order_discount_code_defaults_none
    """
    ctx = setup_arrived_booking("2026-07-01", clock_iso="2026-07-01T18:00:00.000Z")
    h = make_operator_truck_headers(ctx["truck"]["id"])
    order = validate_success(api.create_order(create_order_payload(ctx["booking"]["id"]), h), 201)
    assert order["discount_code"] == "NONE"
    assert order["tip_cents"] == 0


def test_create_order_line_bad_quantity_zero_rejected(api):
    """PRD §3.9: "request well-formedness: required fields present, enum values in range,
    integers within their declared bounds (quantity at least 1 ...) ... any of which fails with
    ERR_INVALID_REQUEST."

    An order line with quantity 0 (below the declared minimum of 1) is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_order_line_bad_quantity_zero_returns_invalid_request
    """
    ctx = setup_arrived_booking("2026-07-02", clock_iso="2026-07-02T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=5)
    add_prep_batch(truck_id, item["id"], units_made=5)
    order = open_order(truck_id, ctx["booking"]["id"])
    h = make_operator_truck_headers(truck_id)
    res = api.create_order_line(create_order_line_payload(order["id"], item["id"], 0), h)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_capture_before_authorize_rejected(api):
    """PRD §3.6: "Capturing a payment is the transition `AUTHORIZED → CAPTURED`; it requires the
    `payment_status` to currently be `AUTHORIZED` (else `ERR_PAYMENT_NOT_AUTHORIZED`)."

    Capturing while payment_status is still UNPAID (never authorized) is rejected with
    ERR_PAYMENT_NOT_AUTHORIZED.

    Design: Corner/state_machines/capture_before_authorize_returns_not_authorized
    """
    ctx = setup_arrived_booking("2026-07-04", clock_iso="2026-07-04T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=5)
    add_prep_batch(truck_id, item["id"], units_made=5)
    order = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order["id"], item["id"], 1)
    h = make_operator_truck_headers(truck_id)
    res = api.capture_payment(order["id"], h)
    validate_error(res, "ERR_PAYMENT_NOT_AUTHORIZED")


def test_settle_before_capture_rejected(api):
    """PRD §3.7: "Four preconditions guard it: the order must be OPEN (else ERR_ORDER_NOT_OPEN);
    it must have at least one order line (else ERR_EMPTY_ORDER); its payment_status must be
    CAPTURED (else ERR_PAYMENT_NOT_CAPTURED)."

    Settling an order whose payment is only AUTHORIZED (not captured) is rejected with
    ERR_PAYMENT_NOT_CAPTURED.

    Design: Corner/state_machines/settle_before_capture_returns_payment_not_captured
    """
    ctx = setup_arrived_booking("2026-07-05", clock_iso="2026-07-05T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=5)
    add_prep_batch(truck_id, item["id"], units_made=5)
    order = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order["id"], item["id"], 1)
    authorize(truck_id, order["id"])
    h = make_operator_truck_headers(truck_id)
    res = api.settle_order(order["id"], h, {"discount_code": "NONE"})
    validate_error(res, "ERR_PAYMENT_NOT_CAPTURED")


def test_depart_with_open_order_blocked(api):
    """PRD §3.4: "Depart. After arriving, the truck departs, the transition ARRIVED -> DEPARTED.
    The booking must currently be ARRIVED (else ERR_BOOKING_NOT_ARRIVED), and no order under this
    booking may still be OPEN (else ERR_OPEN_ORDERS_EXIST)."

    Departing an ARRIVED booking that still has an OPEN order is rejected with
    ERR_OPEN_ORDERS_EXIST; the booking stays ARRIVED.

    Design: Corner/state_machines/depart_with_open_order_blocked
    """
    ctx = setup_arrived_booking("2026-07-03", clock_iso="2026-07-03T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=5)
    add_prep_batch(truck_id, item["id"], units_made=5)
    order = open_order(truck_id, ctx["booking"]["id"])
    add_line(truck_id, order["id"], item["id"], 1)
    h = make_operator_truck_headers(truck_id)
    res = api.depart_booking(ctx["booking"]["id"], h)
    validate_error(res, "ERR_OPEN_ORDERS_EXIST")
    after = validate_success(api.get_booking(ctx["booking"]["id"], DISPATCHER), 200)
    assert after["status"] == "ARRIVED"


def test_add_unlisted_menu_item_to_order_rejected(api):
    """PRD §3.6: "The menu item must be AVAILABLE and must belong to the same truck as the order;
    a line referencing an UNLISTED item, or an item on another truck, is rejected with
    ERR_MENU_ITEM_UNLISTED."

    Adding a line for an item that has been UNLISTED is rejected with ERR_MENU_ITEM_UNLISTED,
    even on an OPEN order.

    Design: Corner/endpoints/add_unlisted_menu_item_to_order_rejected
    """
    ctx = setup_arrived_booking("2026-07-11", clock_iso="2026-07-11T18:00:00.000Z")
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, unit_price_cents=300, par_units=5)
    add_prep_batch(truck_id, item["id"], units_made=5)
    h = make_operator_truck_headers(truck_id)
    validate_success(api.unlist_menu_item(item["id"], h), 200)
    order = open_order(truck_id, ctx["booking"]["id"])
    res = api.create_order_line(create_order_line_payload(order["id"], item["id"], 1), h)
    validate_error(res, "ERR_MENU_ITEM_UNLISTED")
