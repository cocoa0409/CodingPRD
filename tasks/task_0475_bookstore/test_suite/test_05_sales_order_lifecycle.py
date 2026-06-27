"""Sales-order lifecycle: the two independent axes, the cross-axis fulfill
guard, refund credit restoration, and cancel-releases-stock compensation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_sales_order_payload, create_order_line_payload,
    make_member, make_title, receive_stock, seed_credit,
    setup_order_with_line, setup_paid_order, setup_reserved_paid_order,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
ADMIN = TEST_USERS["store_admin_headers"]


def test_order_initial_state_open_unpaid(api):
    """PRD §3.4: "A fresh order is created with `payment_status` `UNPAID` and
    `fulfillment_status` `OPEN`."

    Design: Corner/state_machines/order_initial_state_open_unpaid
    """
    member = make_member()
    mh = make_member_headers(member["id"])
    resp = api.create_sales_order(create_sales_order_payload(member["id"]), mh)
    data = validate_success(resp, expected_status=201)
    assert data["payment_status"] == "UNPAID"
    assert data["fulfillment_status"] == "OPEN"


def test_pay_advances_payment_axis_only(api):
    """PRD §3.4: "The **payment axis**, `payment_status`, moves through `UNPAID`,
    `PAID`, and `REFUNDED`. The **fulfillment axis**, `fulfillment_status`, moves
    through `OPEN`, `RESERVED`, `FULFILLED`, and `CANCELLED`. The two axes evolve
    independently except where a rule explicitly bridges them."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_x_fulfillment_axes
    """
    ctx = setup_order_with_line(list_price_cents=1000, quantity=1, stock_qty=1)
    mh = make_member_headers(ctx["member"]["id"])
    paid = validate_success(api.pay_order(ctx["order"]["id"], mh))
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "OPEN", \
        "paying advances payment axis only; fulfillment axis stays OPEN"


def test_reserve_advances_fulfillment_axis_only(api):
    """PRD §3.5: "**Reserving** an order moves `fulfillment_status` from `OPEN` to
    `RESERVED`".
    PRD §3.4: "The two axes evolve independently except where a rule explicitly
    bridges them."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_x_fulfillment_axes
    """
    ctx = setup_paid_order(list_price_cents=1000, quantity=1, stock_qty=1)
    reserved = validate_success(
        api.reserve_order(ctx["order"]["id"],
                          {"expected_sales_order_version": ctx["order"]["version"]},
                          BOOKSELLER)
    )
    assert reserved["payment_status"] == "PAID", \
        "reserving leaves the payment axis at PAID"
    assert reserved["fulfillment_status"] == "RESERVED"


def test_fulfill_unpaid_order_rejected(api):
    """PRD §3.5: "Fulfillment carries a cross-axis guard: it is allowed only when
    the order is `RESERVED` on the fulfillment axis and, simultaneously, `PAID` on
    the payment axis."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_payment_paid_cross_axis_guard
    """
    ctx = setup_order_with_line(list_price_cents=1000, quantity=1, stock_qty=1)
    mh = make_member_headers(ctx["member"]["id"])
    # Reserve while still UNPAID (reserve has no payment guard).
    reserved = validate_success(
        api.reserve_order(ctx["order"]["id"],
                          {"expected_sales_order_version": ctx["order"]["version"]},
                          BOOKSELLER)
    )
    assert reserved["payment_status"] == "UNPAID"
    resp = api.fulfill_order(ctx["order"]["id"], BOOKSELLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_fulfill_paid_reserved_order_succeeds(api):
    """PRD §3.5: "Fulfilling** an order moves `fulfillment_status` from `RESERVED`
    to `FULFILLED`" and "it is allowed only when the order is `RESERVED` on the
    fulfillment axis and, simultaneously, `PAID` on the payment axis."

    Design: Difficulty/cross_entity_state_dependency/fulfill_requires_payment_paid_cross_axis_guard
    """
    ctx = setup_reserved_paid_order(list_price_cents=1000, quantity=1, stock_qty=1)
    fulfilled = validate_success(api.fulfill_order(ctx["order"]["id"], BOOKSELLER))
    assert fulfilled["fulfillment_status"] == "FULFILLED"
    assert fulfilled["payment_status"] == "PAID"


def test_refund_restores_redeemed_store_credit(api):
    """PRD §3.5: "if the order had redeemed credit (its `credit_redeemed_cents` is
    greater than zero) it appends a `CreditLedgerEntry` with `reason` `ADJUSTMENT`
    and a positive `delta_cents` equal to the redeemed amount, restoring that
    credit, and recomputes the member's `store_credit_cents`".

    Design: Difficulty/compensating_invariant/refund_restores_store_credit_conserved
    """
    member = make_member()
    seed_credit(member["id"], 700)
    title = make_title(list_price_cents=1000)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(
            create_sales_order_payload(member["id"], credit_redeemed_cents=300), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1), mh)
    validate_success(api.pay_order(order["id"], mh))
    # After pay: credit debited by 300 -> 400.
    mid_member = validate_success(api.get_member(member["id"], mh))
    assert mid_member["store_credit_cents"] == 400
    validate_success(api.refund_order(order["id"], BOOKSELLER))
    final_member = validate_success(api.get_member(member["id"], mh))
    assert final_member["store_credit_cents"] == 700, \
        "refund restores the redeemed credit; balance returns to pre-pay value"


def test_refund_cascades_fulfillment_to_cancelled(api):
    """PRD §3.5: "it cascades onto the fulfillment axis by setting
    `fulfillment_status` to `CANCELLED`".
    PRD §3.5: "**Refunding** an order moves `payment_status` from `PAID` to
    `REFUNDED`".

    Design: Difficulty/compensating_invariant/refund_restores_store_credit_conserved
    """
    ctx = setup_paid_order(list_price_cents=1000, quantity=1, stock_qty=1)
    refunded = validate_success(api.refund_order(ctx["order"]["id"], BOOKSELLER))
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["fulfillment_status"] == "CANCELLED"


def test_cancel_reserved_order_releases_stock(api):
    """PRD §3.5: "Cancelling an order that was `RESERVED` additionally releases
    every `RESERVED` stock item on the order's lines back to `AVAILABLE`, clears
    each released copy's `reserved_order_line_id`, recomputes the affected titles'
    `on_hand_qty` and `reserved_qty`".

    Design: Corner/state_machines/cancel_reserved_order_releases_stock_bubble
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 2)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 2), mh)
    reserved = validate_success(
        api.reserve_order(order["id"],
                          {"expected_sales_order_version": order["version"]},
                          BOOKSELLER)
    )
    # On_hand dropped to 0 after reserving both copies.
    mid = validate_success(api.get_title(title["id"], BOOKSELLER))
    assert mid["on_hand_qty"] == 0
    cancelled = validate_success(api.cancel_order(order["id"], mh))
    assert cancelled["fulfillment_status"] == "CANCELLED"
    final_title = validate_success(api.get_title(title["id"], BOOKSELLER))
    assert final_title["on_hand_qty"] == 2, \
        "cancelling a reserved order releases stock back to AVAILABLE"
