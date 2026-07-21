"""Returns: the receipted-vs-non-receipted refund basis, restocking fee on
oversized delivery, full-return refund cascade, the return window, line
matching, and the not-fulfilled-vs-qty-exceeds validation ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, set_clock,
    new_store, new_product, new_inventory, new_member, new_order, add_line,
    capture, ready, fulfill, setup_fulfilled_order, get_inventory, get_line,
    api_client, TEST_USERS,
)

ASSOCIATE = TEST_USERS["associate_headers"]


# ─── refund_receipted_vs_non_receipted_price_basis (queue A) ───

def _fulfilled_then_marked_down():
    """Order fulfilled at clock 2026-07-01 (unit_price snapshot 10000), then clock
    advanced to 2026-07-13 where the SKU's current_price has fallen to 8500."""
    set_clock("2026-07-01T00:00:00Z")
    ctx = setup_fulfilled_order(
        store_kwargs={"name": "Store R1"},
        product_kwargs={"sku": "SKU-R1", "name": "Ceramic Vase", "category": "DECOR",
                        "base_price_cents": 10000, "clearance_floor_cents": 1000,
                        "first_received_at": "2026-06-10T00:00:00Z"},
        allocated_qty=10,
        member_kwargs={"email": "r1@x.com", "full_name": "R One"},
        order_type="CARRYOUT", qty=1)
    set_clock("2026-07-13T00:00:00Z")
    return ctx


def test_non_receipted_refund_uses_current_marked_down_price():
    """PRD §3.7: "The per-unit basis depends on the variant: a `RECEIPTED` return
    refunds against the line's original `unit_price_cents`, while a `NON_RECEIPTED`
    return refunds against the product's `current_price_cents` at approval time —
    today's markdown or clearance price, which can be far lower after the SKU has
    aged. The `base_refund_cents` is that per-unit basis multiplied by
    `returned_qty`."

    Design: Difficulty/dual_variant_calc/refund_receipted_vs_non_receipted_price_basis
    """
    ctx = _fulfilled_then_marked_down()
    data = validate_success(api_client.create_return(
        {"order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "returned_qty": 1, "variant": "NON_RECEIPTED"}, ASSOCIATE), 201)
    assert data["base_refund_cents"] == 8500, f"expected 8500, got {data['base_refund_cents']}"
    assert data["restocking_fee_cents"] == 0, f"expected 0, got {data['restocking_fee_cents']}"
    assert data["refund_amount_cents"] == 8500, f"expected 8500, got {data['refund_amount_cents']}"


def test_receipted_refund_uses_original_paid_unit_price():
    """PRD §3.7: "The per-unit basis depends on the variant: a `RECEIPTED` return
    refunds against the line's original `unit_price_cents`, while a `NON_RECEIPTED`
    return refunds against the product's `current_price_cents` at approval time —
    today's markdown or clearance price, which can be far lower after the SKU has
    aged. The `base_refund_cents` is that per-unit basis multiplied by
    `returned_qty`."

    Design: Difficulty/dual_variant_calc/refund_receipted_vs_non_receipted_price_basis
    """
    ctx = _fulfilled_then_marked_down()
    data = validate_success(api_client.create_return(
        {"order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "returned_qty": 1, "variant": "RECEIPTED"}, ASSOCIATE), 201)
    assert data["base_refund_cents"] == 10000, f"expected 10000, got {data['base_refund_cents']}"
    assert data["refund_amount_cents"] == 10000, f"expected 10000, got {data['refund_amount_cents']}"


# ─── order_not_fulfilled_beats_return_qty_exceeds (queue A) ───

def _captured_not_fulfilled_return_attempt():
    store = new_store(name="Store PC2")
    product = new_product(sku="SKU-PC2", name="Coaster", category="KITCHEN",
                          base_price_cents=800, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 5)
    order = new_order(store["id"], "CARRYOUT")
    add_line(order["id"], product["id"], 2)
    capture(order["id"])  # captured but NOT fulfilled
    return api_client.create_return(
        {"order_id": order["id"], "product_id": product["id"],
         "returned_qty": 99, "variant": "RECEIPTED"}, ASSOCIATE)


def test_not_fulfilled_wins_over_qty_exceeds():
    """PRD §3.7: "The order must be `FULFILLED` before a return can be requested; a
    return against an order not yet fulfilled is rejected with
    `ERR_ORDER_NOT_FULFILLED`."

    Design: Difficulty/priority_pair_validation_conflict/order_not_fulfilled_beats_return_qty_exceeds
    """
    resp = _captured_not_fulfilled_return_attempt()
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FULFILLED.value)


def test_qty_exceeds_suppressed_by_earlier_state_check():
    """PRD §2.1: "Validation across the API follows a fixed priority order, and the
    first check that fails determines the error returned."
    PRD §3.7: "the `returned_qty` may not exceed the line's net sold quantity — the
    ordered quantity minus what has already been returned — otherwise
    `ERR_RETURN_QTY_EXCEEDS`."

    Design: Difficulty/priority_pair_validation_conflict/order_not_fulfilled_beats_return_qty_exceeds
    """
    resp = _captured_not_fulfilled_return_attempt()
    body = resp.json()
    actual = body["data"]["error_id"]
    assert actual == ApiErrorId.ERR_ORDER_NOT_FULFILLED.value, (
        f"state check (order not fulfilled) must win; got {actual}")
    assert actual != ApiErrorId.ERR_RETURN_QTY_EXCEEDS.value, (
        "the fiscal qty-exceeds violation must be suppressed by the earlier state check")


# ─── return_restocking_fee_on_oversized_delivery (queue B) ───

def test_oversized_delivery_return_incurs_restocking_fee():
    """PRD §3.7: "A `restocking_fee_cents` applies only when the order's
    `order_type` is `OVERSIZED_DELIVERY`: it is 15% of the base refund, rounded to a
    whole cent half-up; for every other order type the restocking fee is zero. The
    `refund_amount_cents` the customer receives is the base refund minus the
    restocking fee."

    Design: Corner/calculations/return_restocking_fee_on_oversized_delivery
    """
    set_clock("2026-07-01T00:00:00Z")
    ctx = setup_fulfilled_order(
        store_kwargs={"name": "Store CA3"},
        product_kwargs={"sku": "SKU-CA3", "name": "Bookshelf", "category": "FURNITURE",
                        "base_price_cents": 10000, "clearance_floor_cents": 1000,
                        "first_received_at": "2026-06-25T00:00:00Z"},
        allocated_qty=5, order_type="OVERSIZED_DELIVERY", qty=1)
    data = validate_success(api_client.create_return(
        {"order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "returned_qty": 1, "variant": "RECEIPTED"}, ASSOCIATE), 201)
    assert data["base_refund_cents"] == 10000, f"got {data['base_refund_cents']}"
    assert data["restocking_fee_cents"] == 1500, f"got {data['restocking_fee_cents']}"
    assert data["refund_amount_cents"] == 8500, f"got {data['refund_amount_cents']}"


# ─── full_return_marks_order_payment_refunded (queue B) ───

def test_full_return_approval_restocks_and_refunds():
    """PRD §3.7: "First, the matching order line's `returned_qty` is increased by
    the returned quantity. Second, the matching store-inventory row is restocked:
    its `sold_qty` is decreased and its `on_hand_qty` increased by the returned
    quantity, preserving inventory conservation."
    PRD §3.7: "Finally, if the cumulative returned quantity across all of the
    order's lines now equals the cumulative ordered quantity, the order's
    `payment_status` moves from `CAPTURED` to `REFUNDED`."

    Design: Corner/endpoints/full_return_marks_order_payment_refunded
    """
    set_clock("2026-07-01T00:00:00Z")
    ctx = setup_fulfilled_order(
        store_kwargs={"name": "Store EP2"},
        product_kwargs={"sku": "SKU-EP2", "name": "Clock B", "category": "DECOR",
                        "base_price_cents": 2000, "clearance_floor_cents": 200,
                        "first_received_at": "2026-06-25T00:00:00Z"},
        allocated_qty=5, order_type="CARRYOUT", qty=1)
    ret = validate_success(api_client.create_return(
        {"order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "returned_qty": 1, "variant": "RECEIPTED"}, ASSOCIATE), 201)
    approved = validate_success(api_client.approve_return(ret["id"], ASSOCIATE))
    assert approved["status"] == "APPROVED", f"got {approved['status']}"
    line = get_line(ctx["line"]["id"])
    assert line["returned_qty"] == 1, f"expected returned_qty 1, got {line['returned_qty']}"
    inv = get_inventory(ctx["inventory"]["id"])
    assert inv["on_hand_qty"] == 5, f"expected on_hand 5, got {inv['on_hand_qty']}"
    assert inv["sold_qty"] == 0, f"expected sold 0, got {inv['sold_qty']}"
    order = validate_success(api_client.get_order(ctx["order"]["id"], ASSOCIATE))
    assert order["payment_status"] == "REFUNDED", f"got {order['payment_status']}"


# ─── return_after_window_returns_window_expired (queue B) ───

def test_return_after_thirty_day_window_rejected():
    """PRD §3.7: "The request must fall within 30 days of the order's `fulfilled_at`;
    a later request is rejected with `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_after_window_returns_window_expired
    """
    set_clock("2026-07-01T00:00:00Z")
    ctx = setup_fulfilled_order(
        store_kwargs={"name": "Store V3"},
        product_kwargs={"sku": "SKU-V3", "name": "Quilt", "category": "TEXTILE",
                        "base_price_cents": 4000, "clearance_floor_cents": 400,
                        "first_received_at": "2026-06-25T00:00:00Z"},
        allocated_qty=5, order_type="CARRYOUT", qty=1)
    set_clock("2026-09-01T00:00:00Z")  # > 30 days after fulfilled_at
    resp = api_client.create_return(
        {"order_id": ctx["order"]["id"], "product_id": ctx["product"]["id"],
         "returned_qty": 1, "variant": "RECEIPTED"}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value)


# ─── return_for_unordered_product_line_not_found (queue B) ───

def test_return_for_unordered_product_line_not_found():
    """PRD §3.7: "The pair of `order_id` and `product_id` must match an existing
    order line, otherwise `ERR_LINE_NOT_FOUND`."

    Design: Corner/validations/return_for_unordered_product_line_not_found
    """
    store = new_store(name="Store V7")
    pa = new_product(sku="SKU-V7A", name="Bowl A", category="KITCHEN",
                     base_price_cents=1000, clearance_floor_cents=100,
                     first_received_at="2026-06-25T00:00:00Z")
    pb = new_product(sku="SKU-V7B", name="Bowl B", category="KITCHEN",
                     base_price_cents=1000, clearance_floor_cents=100,
                     first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], pa["id"], 5)
    new_inventory(store["id"], pb["id"], 5)
    order = new_order(store["id"], "CARRYOUT")
    add_line(order["id"], pa["id"], 1)
    capture(order["id"])
    ready(order["id"])
    fulfill(order["id"])
    resp = api_client.create_return(
        {"order_id": order["id"], "product_id": pb["id"],
         "returned_qty": 1, "variant": "RECEIPTED"}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_FOUND.value)
