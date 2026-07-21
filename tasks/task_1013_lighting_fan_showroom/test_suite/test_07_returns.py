"""Returns: line cascade + order recompute, restocking fees, returnability guard (PRD §3.8)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_fixture, create_order, add_line, quote, confirm, pay,
    create_return, create_truck, create_delivery_job, deliver_job, set_clock,
    setup_settled_retail_order_two_lines,
)

SM = TEST_USERS["sm_headers"]


# --------------------------- transitive cascade: approve returns line + recomputes --------
def test_return_approve_marks_line_returned(api):
    """PRD §3.8: "A genuine approval computes the return's `restocking_fee_cents` and cascades."
    PRD §3.8: "Approval also moves the target line's `line_status` from `ACTIVE` to `RETURNED`
    and recomputes the order's `subtotal_final_cents` and `total_final_cents` over the lines
    that remain `ACTIVE`."

    Design: Difficulty/transitive_cascade/return_approve_returns_line_recomputes_order_final
    """
    order, l1, l2, fx = setup_settled_retail_order_two_lines(api, base_price_cents=5000)
    rr = create_return(api, order["id"], l1["id"], "DAMAGE")
    approved = validate_success(api.approve_return_request(rr["id"], SM), 200)
    assert approved["status"] == "APPROVED"
    line = validate_success(api.get_order_line(l1["id"], SM), 200)
    assert line["line_status"] == "RETURNED"


def test_return_approve_recomputes_order_final_over_remaining_lines(api):
    """PRD §3.8: "Approval also moves the target line's `line_status` from `ACTIVE` to
    `RETURNED` and recomputes the order's `subtotal_final_cents` and `total_final_cents` over
    the lines that remain `ACTIVE`."

    Design: Difficulty/transitive_cascade/return_approve_returns_line_recomputes_order_final
    """
    order, l1, l2, fx = setup_settled_retail_order_two_lines(api, base_price_cents=5000)
    rr = create_return(api, order["id"], l1["id"], "DAMAGE")
    api.approve_return_request(rr["id"], SM)
    data = validate_success(api.get_order(order["id"], SM), 200)
    assert data["subtotal_final_cents"] == 5000
    assert data["total_final_cents"] == 5000


# --------------------------- calculations: restocking within / beyond grace ---------------
def test_changed_mind_within_grace_zero_fee_full_refund(api):
    """PRD §3.8: "For `CHANGED_MIND` the percentage depends on how long the customer has had
    the goods: the days since delivery are the whole-day floor of the difference between the
    current clock and the order's delivery window end (treated as zero if the order has no
    delivery), and if that count is at most 14 days the percentage is zero, otherwise it is 0.20."
    PRD §3.8: "Refunding a return acts on an `APPROVED` return, moves it to `REFUNDED`, and
    sets `refund_cents` to the line value minus the `restocking_fee_cents`."

    Design: Corner/calculations/restock_changed_mind_within_grace_zero_fee
    """
    fx = create_fixture(api, sku_base="F-WG", category="PENDANT", base_price_cents=5000, base_wattage=40)
    o = create_order(api, customer_name="WG")
    l1 = add_line(api, o["id"], fx["id"], quantity=2)
    quote(api, o["id"])
    confirm(api, o["id"])
    pay(api, o["id"], "DEPOSIT", 2000)
    rr = create_return(api, o["id"], l1["id"], "CHANGED_MIND")
    approved = validate_success(api.approve_return_request(rr["id"], SM), 200)
    assert approved["restocking_fee_cents"] == 0
    refunded = validate_success(api.refund_return_request(rr["id"], SM), 200)
    assert refunded["refund_cents"] == 10000


def test_changed_mind_beyond_grace_20pct_fee(api):
    """PRD §3.8: "For `CHANGED_MIND` the percentage depends on how long the customer has had
    the goods: the days since delivery are the whole-day floor of the difference between the
    current clock and the order's delivery window end (treated as zero if the order has no
    delivery), and if that count is at most 14 days the percentage is zero, otherwise it is 0.20."
    PRD §3.8: "The `restocking_fee_cents` is the line value times that percentage, rounded
    half-up to whole cents."

    Design: Corner/calculations/restock_changed_mind_beyond_grace_20pct_fee
    """
    truck = create_truck(api, name="TRG")
    fx = create_fixture(api, sku_base="F-BG", category="PENDANT", base_price_cents=5000, base_wattage=40)
    o = create_order(api, customer_name="BG")
    l1 = add_line(api, o["id"], fx["id"], quantity=2)
    quote(api, o["id"])
    confirm(api, o["id"])
    pay(api, o["id"], "SETTLEMENT", 10000)
    dj = create_delivery_job(api, o["id"], truck["id"], "2026-07-02T08:00:00Z", "2026-07-02T10:00:00Z")
    deliver_job(api, dj["id"])
    set_clock(api, "2026-07-20T00:00:00Z")  # 17 whole days after delivery window end
    rr = create_return(api, o["id"], l1["id"], "CHANGED_MIND")
    approved = validate_success(api.approve_return_request(rr["id"], SM), 200)
    assert approved["restocking_fee_cents"] == 2000
    refunded = validate_success(api.refund_return_request(rr["id"], SM), 200)
    assert refunded["refund_cents"] == 8000


# --------------------------- validation: unpaid order not returnable ----------------------
def test_return_approve_unpaid_order_not_returnable(api):
    """PRD §3.8: "Approval is permitted only while the return is `REQUESTED`, only when the
    parent order's `payment_status` is `DEPOSIT_PAID` or `SETTLED`, and only when the target
    line's `line_status` is still `ACTIVE`; a parent whose payment is in neither of those
    states, or a line no longer active, is rejected with `ERR_LINE_NOT_RETURNABLE`."

    Design: Corner/validations/return_approve_unpaid_order_returns_not_returnable
    """
    fx = create_fixture(api, sku_base="F-NR", category="PENDANT", base_price_cents=5000, base_wattage=40)
    o = create_order(api, customer_name="NR")
    l1 = add_line(api, o["id"], fx["id"], quantity=1)
    quote(api, o["id"])
    confirm(api, o["id"])  # CONFIRMED but payment still UNPAID
    rr = create_return(api, o["id"], l1["id"], "DAMAGE")
    resp = api.approve_return_request(rr["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_RETURNABLE.value)
