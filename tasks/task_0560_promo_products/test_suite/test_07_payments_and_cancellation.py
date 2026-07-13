"""Cancellation cascade, escrow refund conservation, and credit constraints."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_issued_po, setup_deposit_paid_order, setup_quoted_order_no_art,
)

AM = TEST_USERS["account_manager_headers"]


# ---- queue A: depth-3 cancel cascade -------------------------------------

def test_order_cancel_cascades_to_line_and_purchase_order(api):
    """PRD 3.9: "Cancellation moves the order to `CANCELLED` and runs a cascade. In the
    first hop, every non-cancelled line of the order is moved to `CANCELLED`. In the
    second hop, for each such line whose active purchase order is in `ISSUED`, that
    purchase order is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/order_cancel_line_po_supplier
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    validate_success(api.cancel_order(ctx["order_id"], AM))
    order = validate_success(api.get_order(ctx["order_id"], AM))
    line = validate_success(api.get_line(ctx["line_id"], AM))
    po = validate_success(api.get_purchase_order(ctx["po_id"], AM))
    assert order["fulfillment_status"] == "CANCELLED"
    assert line["status"] == "CANCELLED"
    assert po["status"] == "CANCELLED"


def test_order_cancel_releases_supplier_reservation_and_refunds_credit(api):
    """PRD 3.9: "In the third hop, each of those cancelled purchase orders releases
    its supplier's reservation by decreasing that supplier's `reserved_blank_qty` by
    the purchase order's `ordered_blank_qty`. Independently, the escrow is refunded:
    the order's `escrow_cents` is returned to the owning customer's `credit_balance_cents`,
    the order's `escrow_cents` is set to 0, and its `payment_status` moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/order_cancel_line_po_supplier
    """
    ctx = setup_issued_po(ordered_blank_qty=210)
    validate_success(api.cancel_order(ctx["order_id"], AM))
    supplier = validate_success(api.get_supplier(ctx["supplier_id"], AM))
    customer = validate_success(api.get_customer(ctx["customer_id"], AM))
    assert supplier["reserved_blank_qty"] == 0
    assert customer["credit_balance_cents"] == 500000, "escrow returned in full on cancel"


# ---- queue A: money conservation on payment then cancel ------------------

def test_cancel_restores_full_customer_credit(api):
    """PRD 2.10: "The `credit_balance_cents` is the currently available credit:
    `total_funded_cents` minus the sum of `escrow_cents` held by that customer's orders
    that have not been refunded. Money is never created or destroyed by a payment —
    it moves from `credit_balance_cents` into an order's `escrow_cents`, and a
    cancellation moves it back."

    Design: Difficulty/compensating_invariant/payment_cancel_conserves_customer_money
    """
    ctx = setup_deposit_paid_order(deposit_amount=60650)
    validate_success(api.cancel_order(ctx["order_id"], AM))
    customer = validate_success(api.get_customer(ctx["customer_id"], AM))
    assert customer["credit_balance_cents"] == 500000
    assert customer["credit_balance_cents"] == customer["total_funded_cents"]


def test_cancel_zeroes_escrow_and_marks_refunded(api):
    """PRD 3.9: "the escrow is refunded: the order's `escrow_cents` is returned to the
    owning customer's `credit_balance_cents`, the order's `escrow_cents` is set to 0, and
    its `payment_status` moves to `REFUNDED`."

    Design: Difficulty/compensating_invariant/payment_cancel_conserves_customer_money
    """
    ctx = setup_deposit_paid_order(deposit_amount=60650)
    validate_success(api.cancel_order(ctx["order_id"], AM))
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["escrow_cents"] == 0
    assert order["payment_status"] == "REFUNDED"


# ---- corner: payment exceeding available credit --------------------------

def test_payment_exceeding_credit_rejected(api):
    """PRD 3.5: "Each payment requires the customer's `credit_balance_cents` to be at
    least `amount_cents`, else `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/cross_cutting_complexity_layers/payment_insufficient_credit_returns_error
    """
    ctx = setup_quoted_order_no_art(initial_credit_cents=1000)
    resp = api.create_payment(ctx["order_id"], {"amount_cents": 60650}, ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    customer = validate_success(api.get_customer(ctx["customer_id"], AM))
    assert order["escrow_cents"] == 0
    assert customer["credit_balance_cents"] == 1000
