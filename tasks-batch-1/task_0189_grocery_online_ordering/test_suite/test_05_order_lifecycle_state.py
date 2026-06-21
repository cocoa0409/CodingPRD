"""Order lifecycle and cross-entity state dependencies.

Difficulty queue A: parallel fulfillment x payment dimensions, cross-entity state
dependencies (order->slot, line->order). Corner queue B: stage preconditions
(lines not resolved, nothing to stage).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_order,
    make_customer_headers,
    make_picker_headers,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_line_ids,
    claim_order,
    pick_line,
    stage_order,
    close_slot,
    ADMIN,
    OPS,
)


def test_order_parallel_dimensions_staged_and_captured(api):
    """PRD §3.2: "An order carries two independent status dimensions. The fulfillment dimension, `fulfillment_status`, walks `PLACED → PICKING → STAGED → HANDED_OFF` ... The payment dimension, `payment_status`, walks `AUTHORIZED → CAPTURED` ... the two dimensions advance independently."

    Design: Difficulty/non_linear_state_machine/nlsm_order_parallel_dimensions
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c5@x.com")
    picker = create_picker(store["id"])
    milk = create_product(store["id"], sku="MILK", name="Milk", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": milk["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    staged = stage_order(order["id"], picker["id"])
    assert staged["fulfillment_status"] == "STAGED"
    assert staged["payment_status"] == "AUTHORIZED", "payment axis still independent"

    resp = api.capture_order(order["id"], OPS)
    data = validate_success(resp)
    assert_order(data)
    # Two axes hold distinct values at once on one row.
    assert data["fulfillment_status"] == "STAGED"
    assert data["payment_status"] == "CAPTURED"


def test_order_payment_dimension_independent_after_cancel(api):
    """PRD §3.2: "The payment dimension, `payment_status`, walks `AUTHORIZED → CAPTURED` and may then evolve to `PARTIALLY_REFUNDED`, `REFUNDED`, or `VOIDED`; the two dimensions advance independently."
    PRD §3.8: "otherwise (payment still `AUTHORIZED`) the payment moves to `VOIDED`."

    Design: Difficulty/non_linear_state_machine/nlsm_order_parallel_dimensions
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c5b@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(customer["id"])))
    # Cancellation drives the fulfillment axis to CANCELLED and, since payment was
    # still AUTHORIZED, the independent payment axis to VOIDED.
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "VOIDED"


def test_order_placement_requires_open_slot(api):
    """PRD §3.1: "a `CLOSED` slot refuses all new placements with `ERR_SLOT_CLOSED`, while orders already booked against it are unaffected."

    Design: Difficulty/cross_entity_state_dependency/cesd_order_place_requires_slot_open
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c13@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=5)
    closed = close_slot(slot["id"])

    resp = api.create_order(
        {"store_id": store["id"], "customer_id": customer["id"], "slot_id": slot["id"],
         "expected_slot_version": closed["version"],
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_CLOSED.value, 409)


def test_order_placement_succeeds_on_open_slot(api):
    """PRD §2.6: "The slot's `status` is `OPEN` while it can still take bookings ... "
    PRD §3.2: "It then satisfies the slot version check and the capacity check of §2.6. On success the server creates one `OrderLine` per entry in `lines` ... sets `fulfillment_status` to `PLACED` ... "

    Design: Difficulty/cross_entity_state_dependency/cesd_order_place_requires_slot_open
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c13b@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=5)
    assert slot["status"] == "OPEN"
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    # Order's valid creation depends on the referenced slot being OPEN.
    assert order["fulfillment_status"] == "PLACED"
    assert order["slot_id"] == slot["id"]


def test_pick_requires_parent_order_picking(api):
    """PRD §3.3: "a pick attempted while the parent order is not `PICKING` is rejected with `ERR_ORDER_NOT_PICKING`."

    Design: Difficulty/cross_entity_state_dependency/cesd_line_pick_requires_order_picking
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c14@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])  # PLACED, never claimed
    ph = make_picker_headers(picker["id"])
    line_id = get_line_ids(order["id"], headers=ph)[0]

    resp = api.pick_order_line(line_id, {"picked_qty": 1}, ph)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PICKING.value, 409)


def test_pick_succeeds_once_order_is_picking(api):
    """PRD §3.3: "To pick a line, a `Picker` records the actual pick on a `PENDING` line whose parent order is `PICKING`, advancing the line from `PENDING` to `PICKED`."
    PRD §3.3: "Picking recomputes the line's `final_line_cents` from the recorded `picked_qty` or `actual_weight_kg`."

    Design: Difficulty/cross_entity_state_dependency/cesd_line_pick_requires_order_picking
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c14b@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 2}])
    ph = make_picker_headers(picker["id"])
    line_id = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])  # order now PICKING

    data = validate_success(api.pick_order_line(line_id, {"picked_qty": 2}, ph))
    # The line transition is only valid because the parent Order is PICKING.
    assert data["status"] == "PICKED"
    assert data["final_line_cents"] == 698, "349 * 2"


def test_stage_with_pending_line_rejected(api):
    """PRD §3.5: "Staging is admitted only when the order is `PICKING` ... when every line has reached a terminal state — none may still be `PENDING`, or the stage is rejected with `ERR_LINES_NOT_RESOLVED` ... "

    Design: Corner/state_machines/sm_stage_with_pending_line_rejected
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc6@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": a["id"], "requested_qty": 1},
         {"product_id": b["id"], "requested_qty": 1}],
    )
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], product_id=a["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    pick_line(a_line, picker["id"], picked_qty=1)  # B still PENDING

    resp = api.stage_order(order["id"], ph)
    validate_error(resp, ApiErrorId.ERR_LINES_NOT_RESOLVED.value, 409)


def test_stage_when_all_lines_out_of_stock_rejected(api):
    """PRD §3.5: "and when at least one line is `PICKED` or `SUBSTITUTED`, or the stage is rejected with `ERR_NOTHING_TO_STAGE`."

    Design: Corner/state_machines/sm_stage_all_out_of_stock_nothing_to_stage
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="cc7@x.com")
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    ph = make_picker_headers(picker["id"])
    line_id = get_line_ids(order["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    validate_success(api.out_of_stock_order_line(line_id, ph))  # pre-capture OOS

    resp = api.stage_order(order["id"], ph)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_STAGE.value, 409)
