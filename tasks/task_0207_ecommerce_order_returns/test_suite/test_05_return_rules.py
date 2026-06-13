"""Return-opening business rules, validation priority, cross-entity gates (PRD §3.6).

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check
(return_qty == shipped), cross_entity_state_dependency (ship needs CAPTURED,
return needs DELIVERED), resource_temporal_overlap (return-window boundary).
Corner queue: validations (exchange target required, exchange OOS, insufficient
credit, warehouse rejects returns, reservation mismatch).
"""
from test_helpers import (
    fixtures as fx,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    open_return_payload,
    create_shipment_payload,
    restock_payload,
    credit_adjustment_payload,
)

DELIVER_CLOCK = "2026-06-05T00:00:00Z"
ACT_CLOCK = "2026-06-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Priority-pair conflicts (PRD §2.9 / §3.6)
# ---------------------------------------------------------------------------
def test_invalid_state_beats_return_window_on_authorized_order(api):
    """PRD §2.9: "Only after all of these pass does the system evaluate the
    business-rule checks (the 422-class rules described throughout §3), in the
    relative order those narratives specify."
    PRD §3.6: "The order's payment_status must be CAPTURED, and every return line's
    order line must belong to the order named in the path."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_return_window_closed_on_returns
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 2000, "tax_rate_bps": 0,
                           "return_window_days": 1},
        qty=1, on_hand_qty=10)
    fx.set_clock("2026-07-01T00:00:00Z")  # window would also be closed if reached
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_return_on_authorized_order_is_invalid_state_even_when_window_open(api):
    """PRD §2.9: "Only after all of these pass does the system evaluate the
    business-rule checks (the 422-class rules described throughout §3), in the
    relative order those narratives specify."
    PRD §3.6: "The order's payment_status must be CAPTURED, and every return line's
    order line must belong to the order named in the path."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_return_window_closed_on_returns
    """
    # Order is AUTHORIZED (not captured); product window is wide and clock is fresh,
    # so the temporal rule could NOT fire — only the state rule applies, proving the
    # state check is reached before any business-rule (422) check.
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 2000, "tax_rate_bps": 0,
                           "return_window_days": 365},
        qty=1, on_hand_qty=10)
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_final_sale_beats_return_window_closed(api):
    """PRD §3.6: "No return line may reference a product whose final_sale is true;
    such an attempt is rejected with ERR_FINAL_SALE_NOT_RETURNABLE (HTTP 422)."
    PRD §3.6: "Among these business checks the final-sale rule is evaluated first,
    then the return-window check, then the quantity-against-shipped check, then the
    exchange-target requirement."

    Design: Difficulty/priority_pair_validation_conflict/final_sale_beats_return_window_closed_on_returns
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 2000, "tax_rate_bps": 0,
                           "return_window_days": 1, "final_sale": True},
        qty=1, on_hand_qty=10, delivered_clock="2026-06-01T00:00:00Z")
    fx.set_clock("2026-07-01T00:00:00Z")  # window closed too
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_FINAL_SALE_NOT_RETURNABLE.value)


def test_final_sale_rejected_even_when_window_open(api):
    """PRD §3.6: "No return line may reference a product whose final_sale is true;
    such an attempt is rejected with ERR_FINAL_SALE_NOT_RETURNABLE (HTTP 422)."
    PRD §3.6: "Among these business checks the final-sale rule is evaluated first,
    then the return-window check".

    Design: Difficulty/priority_pair_validation_conflict/final_sale_beats_return_window_closed_on_returns
    """
    # Window is wide open (window 365, fresh clock); only the final-sale rule can
    # fire, proving final-sale is the first business check.
    fx.set_clock("2026-06-01T00:00:00Z")
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 2000, "tax_rate_bps": 0,
                           "return_window_days": 365, "final_sale": True},
        qty=1, on_hand_qty=10, delivered_clock="2026-06-01T00:00:00Z")
    fx.set_clock("2026-06-05T00:00:00Z")  # well within the window
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_FINAL_SALE_NOT_RETURNABLE.value)


# ---------------------------------------------------------------------------
# return_qty vs shipped_qty boundary (PRD §3.6)
# ---------------------------------------------------------------------------
def test_return_qty_equal_to_shipped_is_accepted(api):
    """PRD §3.6: "For each return line, the requested return_qty plus the quantity
    already returned for that order line must not exceed the order line's shipped_qty
    — one cannot return more than was delivered — and a violation is rejected with
    ERR_RETURN_QTY_EXCEEDS_SHIPPED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/return_qty_equals_shipped_passes_plus_one_rejected_on_returns
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=2, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 2}])
    assert rma["status"] == "REQUESTED", "return_qty 2 == shipped_qty 2 is accepted"


def test_return_qty_exceeds_shipped_by_one_is_rejected(api):
    """PRD §3.6: "For each return line, the requested return_qty plus the quantity
    already returned for that order line must not exceed the order line's shipped_qty
    — one cannot return more than was delivered — and a violation is rejected with
    ERR_RETURN_QTY_EXCEEDS_SHIPPED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/return_qty_equals_shipped_passes_plus_one_rejected_on_returns
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=2, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 3}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED.value)


# ---------------------------------------------------------------------------
# Cross-entity state dependencies (PRD §3.5 / §3.6)
# ---------------------------------------------------------------------------
def test_ship_requires_order_payment_captured(api):
    """PRD §3.5: "It additionally requires that the parent order's payment_status
    already be CAPTURED: goods may never ship before payment is captured, and an
    attempt to ship an order that is not yet captured is rejected with
    ERR_PAYMENT_NOT_CAPTURED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_order_payment_captured_shipment_to_order
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    shipment, _ = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 1)
    resp = api.ship_shipment(shipment["id"], fx.OP)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED.value)


def test_ship_succeeds_once_payment_captured(api):
    """PRD §3.5: "It additionally requires that the parent order's payment_status
    already be CAPTURED: goods may never ship before payment is captured".
    PRD §3.5: "Dispatching a parcel — the ship action — is restricted to a
    WarehouseOperator and is permitted only when the shipment is PENDING."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_order_payment_captured_shipment_to_order
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    shipment, _ = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 1)
    shipped = fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    assert shipped["status"] == "SHIPPED", "ship is allowed once payment is CAPTURED"


def test_return_requires_a_delivered_shipment(api):
    """PRD §3.6: "For each return line, the return window must be open: some shipment
    carrying that line must be DELIVERED, and the current logical clock must be no
    later than that shipment's delivered_at plus the product's return_window_days
    days, with the boundary day inclusive; a window that has no delivered shipment for
    the line, or whose deadline has passed, is rejected with
    ERR_RETURN_WINDOW_CLOSED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/return_requires_shipment_delivered_returnauthorization_to_shipment
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_shipped_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value)


def test_return_opens_once_a_shipment_is_delivered(api):
    """PRD §3.6: "For each return line, the return window must be open: some shipment
    carrying that line must be DELIVERED, and the current logical clock must be no
    later than that shipment's delivered_at plus the product's return_window_days
    days, with the boundary day inclusive".
    PRD §3.6: "Once an order is paid for and its goods have arrived, the owning
    Customer (or a StoreAdmin) may open a Return Merchandise Authorization against it."

    Design: Difficulty/cross_entity_state_dependency/return_requires_shipment_delivered_returnauthorization_to_shipment
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    assert rma["status"] == "REQUESTED", \
        "with a DELIVERED shipment anchoring an open window, the return opens"


# ---------------------------------------------------------------------------
# Return-window time-interval boundary (PRD §3.6)
# ---------------------------------------------------------------------------
def test_return_window_open_on_inclusive_upper_boundary_day(api):
    """PRD §3.6: "the current logical clock must be no later than that shipment's
    delivered_at plus the product's return_window_days days, with the boundary day
    inclusive".

    Design: Difficulty/resource_temporal_overlap/return_window_closed_interval_boundary_inclusive_on_returns
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock="2026-06-01T00:00:00Z")
    fx.set_clock("2026-07-01T00:00:00Z")  # exactly day +30 — inclusive upper bound
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    assert rma["status"] == "REQUESTED", "day +30 is inside the closed window"


def test_return_window_closed_one_day_past_boundary(api):
    """PRD §3.6: "the current logical clock must be no later than that shipment's
    delivered_at plus the product's return_window_days days, with the boundary day
    inclusive; a window that has no delivered shipment for the line, or whose deadline
    has passed, is rejected with ERR_RETURN_WINDOW_CLOSED (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/return_window_closed_interval_boundary_inclusive_on_returns
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock="2026-06-01T00:00:00Z")
    fx.set_clock("2026-07-02T00:00:00Z")  # day +31 — outside the closed window
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("NO_LONGER_WANTED", "REFUND",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value)


# ---------------------------------------------------------------------------
# Corner validations
# ---------------------------------------------------------------------------
def test_exchange_without_target_rejected(api):
    """PRD §3.6: "When the resolution is EXCHANGE, every return line's
    exchange_product_id must be non-null and must reference a product that is not
    final-sale; a missing or final-sale exchange target is rejected with
    ERR_EXCHANGE_TARGET_REQUIRED (HTTP 422)."

    Design: Corner/validations/exchange_without_target_returns_exchange_target_required
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 2000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    headers = make_customer_headers(ctx["customer"]["id"])
    resp = api.open_return(
        ctx["order"]["id"],
        open_return_payload("WRONG_ITEM", "EXCHANGE",
                            [{"order_line_id": ctx["line"]["id"], "return_qty": 1}]),
        headers)
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_TARGET_REQUIRED.value)


def test_exchange_settle_out_of_stock_rejected(api):
    """PRD §3.8: "Settling an EXCHANGE return advances the status from APPROVED to
    EXCHANGED and requires that the exchange product have an available_qty of at
    least the return_qty in at least one warehouse; insufficient stock is rejected
    with ERR_EXCHANGE_OUT_OF_STOCK (HTTP 422)."

    Design: Corner/validations/exchange_settle_out_of_stock_returns_exchange_out_of_stock
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    p1 = fx.create_product(unit_price_cents=2000, tax_rate_bps=0, return_window_days=30)
    p2 = fx.create_product(unit_price_cents=2000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(p1["id"], warehouse["id"], 10)
    # p2 is intentionally NOT stocked → available_qty 0.

    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], p1["id"], 1)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])
    shipment, _ = fx.create_pending_shipment(order["id"], warehouse["id"], line["id"], 1)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    fx.set_clock(DELIVER_CLOCK)
    fx.get_success_data(api.deliver_shipment(shipment["id"], fx.OP))
    fx.set_clock(ACT_CLOCK)

    rma = fx.open_approve_return(
        order["id"], customer["id"], "WRONG_ITEM", "EXCHANGE",
        [{"order_line_id": line["id"], "return_qty": 1, "exchange_product_id": p2["id"]}])
    resp = api.settle_return(rma["id"], fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_OUT_OF_STOCK.value)


def test_credit_redemption_below_zero_rejected(api):
    """PRD §3.9: "The adjustment writes a CreditLedgerEntry and recomputes the
    customer's store_credit_cents, but it is rejected with
    ERR_INSUFFICIENT_STORE_CREDIT (HTTP 422) if applying it would drive the balance
    below 0."

    Design: Corner/validations/credit_redemption_below_zero_returns_insufficient_store_credit
    """
    customer = fx.create_customer()
    resp = api.create_credit_adjustment(
        customer["id"], credit_adjustment_payload(-500, "REDEMPTION"), fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value)


def test_restock_to_non_accepting_warehouse_rejected(api):
    """PRD §3.9: "The request supplies the target warehouse_id, which must have
    accepts_returns set to true; a warehouse that does not accept returns is rejected
    with ERR_WAREHOUSE_REJECTS_RETURNS (HTTP 422)."

    Design: Corner/validations/restock_to_non_accepting_warehouse_returns_warehouse_rejects_returns
    """
    customer = fx.create_customer()
    ship_wh = fx.create_warehouse(fulfillment_priority=1)
    no_returns_wh = fx.create_warehouse(fulfillment_priority=2, accepts_returns=False)
    product = fx.create_product(unit_price_cents=2000, tax_rate_bps=0,
                                restocking_fee_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], ship_wh["id"], 10)

    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])
    shipment, _ = fx.create_pending_shipment(order["id"], ship_wh["id"], line["id"], 1)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))
    fx.set_clock(DELIVER_CLOCK)
    fx.get_success_data(api.deliver_shipment(shipment["id"], fx.OP))
    fx.set_clock(ACT_CLOCK)

    rma = fx.open_approve_settle_return(
        order["id"], customer["id"], "DEFECTIVE", "REFUND",
        [{"order_line_id": line["id"], "return_qty": 1}])
    resp = api.restock_return(rma["id"], restock_payload(no_returns_wh["id"]), fx.OP)
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_REJECTS_RETURNS.value)


def test_shipment_line_reservation_qty_mismatch_rejected(api):
    """PRD §3.5: "For each attached shipment line, the qty must equal the referenced
    reservation's qty, the referenced reservation must be in HELD status and belong
    to the order, and the shipment's warehouse must match the reservation's
    warehouse; any violation is rejected with ERR_RESERVATION_MISMATCH (HTTP 422)."

    Design: Corner/validations/shipment_line_reservation_mismatch_returns_reservation_mismatch
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    reservations = fx.get_line_reservations(ctx["line"]["id"], ctx["warehouse"]["id"])
    res_id = reservations[0]["id"]
    resp = api.create_shipment(
        ctx["order"]["id"],
        create_shipment_payload(ctx["warehouse"]["id"],
                                [{"reservation_id": res_id, "qty": 2}]),
        fx.OP)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_MISMATCH.value)
