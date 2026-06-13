"""Split-tender capture, refund cascade, and money conservation.

Difficulty queue A: split-tender nested-min allocation, out-of-stock refund
depth-3 cascade, captured-money conservation invariant. Corner queue B:
ebt-not-accepted gate, immediate-consistency capture, refund discovery channel,
double-capture state error.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_order,
    assert_split_tender_invariants,
    assert_net_captured_identity,
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
    capture_order,
    setup_single_unit_order_staged,
    setup_single_unit_order_captured,
    ADMIN,
    OPS,
)


def _build_ebt_order_staged(email, snap_balance, tip_cents):
    """Store(ebt on) + customer(snap_balance) + picker + EBT banana(199 c/kg WEIGHT)
    + EBT milk(349 UNIT) + cap-1 slot; place, claim, pick banana@1.83/milk qty2,
    stage. Returns (store, customer, picker, order, milk_line, ban_line)."""
    store = create_store(ebt_enabled=True)
    customer = create_customer(email=email, snap_ebt_balance_cents=snap_balance)
    picker = create_picker(store["id"])
    banana = create_product(store["id"], sku="BAN", name="Bananas",
                            pricing_mode="WEIGHT", unit_price_cents=199, ebt_eligible=True)
    milk = create_product(store["id"], sku="MILK", name="Milk",
                          pricing_mode="UNIT", unit_price_cents=349, ebt_eligible=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": banana["id"], "requested_qty": 1, "estimated_weight_kg": 1.50},
         {"product_id": milk["id"], "requested_qty": 2}],
        tip_cents=tip_cents,
    )
    ph = make_picker_headers(picker["id"])
    ban_line = get_line_ids(order["id"], product_id=banana["id"], headers=ph)[0]
    milk_line = get_line_ids(order["id"], product_id=milk["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    pick_line(ban_line, picker["id"], actual_weight_kg=1.83)
    pick_line(milk_line, picker["id"], picked_qty=2)
    stage_order(order["id"], picker["id"])
    return store, customer, picker, order, milk_line, ban_line


def test_split_tender_nested_min_overflow_to_card(api):
    """PRD §3.6: "The EBT bucket is filled first: `ebt_charged_cents` is the smaller of `final_ebt_eligible_cents` and the customer's `snap_ebt_balance_cents`. The card bucket then takes the remainder: `card_charged_cents` is `final_total_cents` minus `ebt_charged_cents`, which absorbs the tip, all ineligible goods, and any EBT-eligible value that exceeded the benefit balance."
    PRD §3.6: "it debits the customer's `snap_ebt_balance_cents` by `ebt_charged_cents` ... "

    Design: Difficulty/combinatorial_formula/cf_split_tender_nested_min
    """
    store, customer, picker, order, milk_line, ban_line = _build_ebt_order_staged(
        "c3@x.com", snap_balance=800, tip_cents=500)
    # final_ebt_eligible = banana 364 + milk 698 = 1062; final_total = 1062 + 500 tip = 1562.
    resp = api.capture_order(order["id"], OPS)
    data = validate_success(resp)
    assert_order(data)
    assert data["ebt_charged_cents"] == 800, "min(1062, 800)"
    assert data["card_charged_cents"] == 762, "1562 - 800"
    assert data["payment_status"] == "CAPTURED"
    assert_split_tender_invariants(data)

    cust = validate_success(api.get_customer(customer["id"], OPS))
    assert cust["snap_ebt_balance_cents"] == 0, "balance debited by 800"


def test_split_tender_payment_record_created(api):
    """PRD §3.6: "creates exactly one `Payment` record ... it records `ebt_amount_cents` (equal to the order's `ebt_charged_cents` at capture), `card_amount_cents` (equal to the order's `card_charged_cents`), and `grand_total_cents` (their sum, equal to the order's `final_total_cents`)."

    Design: Difficulty/combinatorial_formula/cf_split_tender_nested_min
    """
    store, customer, picker, order, milk_line, ban_line = _build_ebt_order_staged(
        "c3b@x.com", snap_balance=800, tip_cents=500)
    capture_order(order["id"])
    data, _meta = validate_paginated(api.list_payments(OPS, params={"order_id": order["id"]}))
    assert len(data) == 1, "exactly one Payment created at capture"
    pay = data[0]
    assert pay["ebt_amount_cents"] == 800
    assert pay["card_amount_cents"] == 762
    assert pay["grand_total_cents"] == 1562


def test_out_of_stock_refund_depth3_cascade(api):
    """PRD §3.7: "The correction reads the line's current `final_line_cents` — the amount that was captured for that line — as the refund amount, then sets the line's `final_line_cents` to 0. It creates a `Refund` whose `amount_cents` equals that captured amount ... It then increases the order's `refunded_total_cents` by the refunded amount ... "
    PRD §3.8: "the system moves `payment_status` from `CAPTURED` to `PARTIALLY_REFUNDED` while some captured value remains ... and recomputes `net_captured_cents` accordingly."

    Design: Difficulty/transitive_cascade/tc_out_of_stock_refund_depth3
    """
    store, customer, picker, order, milk_line, ban_line = _build_ebt_order_staged(
        "c7@x.com", snap_balance=800, tip_cents=500)
    capture_order(order["id"])  # ebt 800, card 762, net 1562
    resp = api.out_of_stock_order_line(milk_line, OPS)
    line = validate_success(resp)
    assert line["status"] == "OUT_OF_STOCK"

    order_after = validate_success(api.get_order(order["id"], OPS))
    assert order_after["refunded_total_cents"] == 698, "milk captured amount refunded"
    assert order_after["payment_status"] == "PARTIALLY_REFUNDED"
    assert order_after["net_captured_cents"] == 864, "1562 - 698"
    assert_net_captured_identity(order_after)


def test_out_of_stock_refund_creates_refund_record_and_zeroes_line(api):
    """PRD §3.7: "The correction reads the line's current `final_line_cents` — the amount that was captured for that line — as the refund amount, then sets the line's `final_line_cents` to 0. It creates a `Refund` whose `amount_cents` equals that captured amount, whose `order_id` and `order_line_id` point at the order and the out-of-stock line, and whose `reason` is `OUT_OF_STOCK` ... "

    Design: Difficulty/transitive_cascade/tc_out_of_stock_refund_depth3
    """
    store, customer, picker, order, milk_line, ban_line = _build_ebt_order_staged(
        "c7b@x.com", snap_balance=800, tip_cents=500)
    capture_order(order["id"])
    api.out_of_stock_order_line(milk_line, OPS)  # milk captured 698

    line_after = validate_success(api.get_order_line(milk_line, OPS))
    assert line_after["final_line_cents"] == 0, "first cascade link zeroes the line"

    refunds, _meta = validate_paginated(
        api.list_refunds(OPS, params={"order_id": order["id"]}))
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 698, "Refund equals the captured line amount"
    assert refunds[0]["order_line_id"] == milk_line
    assert refunds[0]["reason"] == "OUT_OF_STOCK"


def test_captured_money_conservation_partial_refund(api):
    """PRD §3.8: "The order's `net_captured_cents` is its `ebt_charged_cents` plus its `card_charged_cents` minus its `refunded_total_cents`."
    PRD §3.8: "the system moves `payment_status` from `CAPTURED` to `PARTIALLY_REFUNDED` while some captured value remains — that is, while `refunded_total_cents` is greater than 0 but still strictly less than the captured total `ebt_charged_cents` plus `card_charged_cents`, leaving `net_captured_cents` above 0 ... "

    Design: Difficulty/compensating_invariant/ci_payment_tender_conservation
    """
    # Two non-EBT lines; one goes out of stock -> partial refund, money conserved.
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c18b@x.com", snap_ebt_balance_cents=0)
    picker = create_picker(store["id"])
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=698, ebt_eligible=False)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500, ebt_eligible=False)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1},
                         {"product_id": b["id"], "requested_qty": 1}], tip_cents=0)
    ph = make_picker_headers(picker["id"])
    a_line = get_line_ids(order["id"], product_id=a["id"], headers=ph)[0]
    b_line = get_line_ids(order["id"], product_id=b["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"], window_start="2026-06-15T07:00:00Z",
                window_end="2026-06-15T07:45:00Z")
    pick_line(a_line, picker["id"], picked_qty=1)
    pick_line(b_line, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    captured = capture_order(order["id"])  # card 1198, net 1198
    assert captured["net_captured_cents"] == 1198

    api.out_of_stock_order_line(a_line, OPS)  # refund 698
    after = validate_success(api.get_order(order["id"], OPS))
    assert after["payment_status"] == "PARTIALLY_REFUNDED"
    assert after["refunded_total_cents"] == 698
    assert after["net_captured_cents"] == 500, "1198 - 698"
    # Conservation: no money drift at the partial-refund midpoint.
    assert (after["net_captured_cents"] + after["refunded_total_cents"]
            == after["ebt_charged_cents"] + after["card_charged_cents"])


def test_captured_money_conservation_full_refund(api):
    """PRD §3.8: "The order's `net_captured_cents` is its `ebt_charged_cents` plus its `card_charged_cents` minus its `refunded_total_cents`."
    PRD §3.8: "When `refunded_total_cents` reaches the full captured total `ebt_charged_cents` plus `card_charged_cents`, the order moves to `REFUNDED` and `net_captured_cents` becomes 0."

    Design: Difficulty/compensating_invariant/ci_payment_tender_conservation
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c18@x.com", snap_ebt_balance_cents=0)
    picker = create_picker(store["id"])
    product = create_product(store["id"], unit_price_cents=698, ebt_eligible=False)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}], tip_cents=0)
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"], window_start="2026-06-15T07:00:00Z",
                window_end="2026-06-15T07:45:00Z")
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    captured = capture_order(order["id"])  # ebt 0, card 698, net 698
    assert captured["ebt_charged_cents"] == 0
    assert captured["card_charged_cents"] == 698

    api.out_of_stock_order_line(line_id, OPS)
    order_after = validate_success(api.get_order(order["id"], OPS))
    assert order_after["refunded_total_cents"] == 698
    assert order_after["net_captured_cents"] == 0
    assert order_after["payment_status"] == "REFUNDED"
    # Conservation: net_captured + refunded == captured total (no money drift).
    assert (order_after["net_captured_cents"] + order_after["refunded_total_cents"]
            == order_after["ebt_charged_cents"] + order_after["card_charged_cents"])


def test_capture_blocked_when_store_ebt_disabled(api):
    """PRD §3.6: "if the store's `ebt_enabled` is false, the order's `final_ebt_eligible_cents` must be 0, or the capture is rejected with `ERR_EBT_NOT_ACCEPTED`."

    Design: Corner/validations/val_ebt_not_accepted_at_capture
    """
    store = create_store(ebt_enabled=False)
    customer = create_customer(email="cc13@x.com", snap_ebt_balance_cents=100000)
    picker = create_picker(store["id"])
    product = create_product(store["id"], unit_price_cents=349, ebt_eligible=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])

    resp = api.capture_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_EBT_NOT_ACCEPTED.value, 409)


def test_capture_immediately_visible_in_response(api):
    """PRD §3.6: "it ... sets the order's `net_captured_cents` to the order's `final_total_cents`."
    PRD §3.6: "A `StoreOps` operator captures payment on a staged order, advancing `payment_status` from `AUTHORIZED` to `CAPTURED`."

    Design: Corner/consistency_model/immediate_capture_visible_in_same_response
    """
    store, customer, picker, product, slot, order, line_id = setup_single_unit_order_staged(
        unit_price_cents=349, picked_qty=1, email="cc30@x.com")
    resp = api.capture_order(order["id"], OPS)
    data = validate_success(resp)
    assert data["payment_status"] == "CAPTURED"
    assert data["net_captured_cents"] == 349


def test_refund_discoverable_by_order_filter(api):
    """PRD §3.9: "Refund records may be listed and filtered by `order_id` or by `order_line_id`, or fetched individually, and read back in creation order they reconstruct the chronological refund history that drives the order's `refunded_total_cents`."

    Design: Corner/endpoints/ep_fk_reverse_refunds_by_order
    """
    store = create_store()
    customer = create_customer(email="cc18@x.com", snap_ebt_balance_cents=0)
    picker = create_picker(store["id"])
    product = create_product(store["id"], unit_price_cents=698)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 1}])
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=1)
    stage_order(order["id"], picker["id"])
    capture_order(order["id"])
    api.out_of_stock_order_line(line_id, OPS)

    data, _meta = validate_paginated(api.list_refunds(OPS, params={"order_id": order["id"]}))
    assert len(data) == 1
    assert data[0]["amount_cents"] == 698
    assert data[0]["reason"] == "OUT_OF_STOCK"


def test_double_capture_rejected_invalid_order_state(api):
    """PRD §3.6: "Capture is admitted only when the payment is `AUTHORIZED` (otherwise `ERR_INVALID_ORDER_STATE`) and the order is `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`)."

    Design: Corner/errors/err_invalid_order_state_double_capture
    """
    store, customer, picker, product, slot, order, line_id = setup_single_unit_order_captured(
        unit_price_cents=349, picked_qty=1, email="cc23@x.com")
    resp = api.capture_order(order["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)
