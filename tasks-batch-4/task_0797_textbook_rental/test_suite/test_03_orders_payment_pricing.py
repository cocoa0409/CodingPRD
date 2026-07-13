"""Order pricing, the independent payment/fulfilment axes, pay-then-cancel money
conservation, and ebook access delivery. Mixes difficulty and corner instances."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_catalog_item_payload, create_customer_payload, create_order_payload,
    TEST_USERS, make_customer_headers,
    set_clock, create_catalog_item, create_inventory_unit, create_funded_customer,
    create_customer, get_customer,
    setup_paid_confirmed_rental, setup_active_subscription,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Difficulty: Order parallel payment / fulfilment axes ─────────────

def test_pay_moves_only_payment_axis(api):
    """PRD 3.3: "Every order starts with `payment_status` of `UNPAID` and
    `fulfillment_status` of `PENDING`; these two axes move independently."
    PRD 3.3: "On success the system appends a `WalletTransaction` of `kind`
    `ORDER_CHARGE` for the negative of `quoted_charge_cents` and moves `payment_status`
    from `UNPAID` to `PAID`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item()
    create_inventory_unit(cat["id"], condition_grade="GOOD")
    cust = create_funded_customer(50000, email="pa@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    paid = validate_success(api.pay_order(order["id"], headers), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "PENDING", paid["fulfillment_status"]


def test_confirm_moves_only_fulfillment_axis(api):
    """PRD 3.4: "Confirming a `BUY` order instead drives the copy's `status` from
    `AVAILABLE` directly to `SOLD` and moves the order's `fulfillment_status` from
    `CONFIRMED` straight to `DELIVERED` in a single step; no rental is created."
    PRD 3.3: "these two axes move independently."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    ctx = setup_paid_confirmed_rental(email="pb@x.com")
    order = validate_success(api.get_order(ctx["order"]["id"], WAREHOUSE), 200)
    assert order["fulfillment_status"] == "CONFIRMED", order["fulfillment_status"]
    assert order["payment_status"] == "PAID"


# ─── Difficulty: wallet money conserved on pay then cancel ────────────

def test_pay_then_cancel_sets_refunded_terminal_states(api):
    """PRD 3.3: "A valid cancel moves `fulfillment_status` to `CANCELLED`; if the order
    had already been paid, the system appends a compensating `WalletTransaction` of
    `kind` `ORDER_REFUND` for the positive `quoted_charge_cents`, adds that amount to the
    order's `refunded_cents`, and sets `payment_status` to `REFUNDED`."

    Design: Difficulty/compensating_invariant/wallet_money_conserved_on_pay_then_cancel
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item()
    cust = create_funded_customer(20000, email="wc1@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    validate_success(api.pay_order(order["id"], headers), 200)
    cancelled = validate_success(api.cancel_order(order["id"], headers), 200)
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["fulfillment_status"] == "CANCELLED"


def test_pay_then_cancel_restores_wallet_balance(api):
    """PRD 2.6: "A customer's `wallet_credit_cents` is always the exact sum of the
    `amount_cents` of every `WalletTransaction` whose `customer_id` is that customer; it
    is recomputed on every ledger append and is order-independent."
    PRD 3.3: "if the order had already been paid, the system appends a compensating
    `WalletTransaction` of `kind` `ORDER_REFUND` for the positive `quoted_charge_cents`".

    Design: Difficulty/compensating_invariant/wallet_money_conserved_on_pay_then_cancel
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item()
    cust = create_funded_customer(20000, email="wc2@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    validate_success(api.pay_order(order["id"], headers), 200)   # ORDER_CHARGE -6000
    validate_success(api.cancel_order(order["id"], headers), 200)  # ORDER_REFUND +6000
    assert get_customer(cust["id"])["wallet_credit_cents"] == 20000


# ─── Corner: pricing & payment ────────────────────────────────────────

def test_order_charge_member_discount_applied(api):
    """PRD 3.3: "For a `RENT` order the quote is the title's `rental_base_cents`
    multiplied by the term multiplier for the chosen term — 0.5 for a 30-day term, 0.75
    for 60 days, 1.0 for 90 days, and 1.25 for 120 days — multiplied by one minus the
    member discount, then rounded half up to whole cents."
    PRD 3.3: "The member discount is the `rental_discount_pct` snapshotted on the
    customer's `ACTIVE` subscription when one exists, and zero otherwise."

    Design: Corner/calculations/order_charge_member_discount_applied
    """
    ctx = setup_active_subscription(
        tier="SOLUTIONS", monthly_fee_cents=2499, rental_discount_pct=0.15,
        includes_solutions=True, term_months=1, start_clock="2026-03-01T00:00:00Z",
        start_date="2026-03-01T00:00:00Z", email="md@x.com")
    cat = create_catalog_item()
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), ctx["headers"]), 201)
    # round_half_up(6000 * 1.0 * (1 - 0.15)) = 5100
    assert order["quoted_charge_cents"] == 5100, order["quoted_charge_cents"]


def test_ebook_pay_grants_access_window(api):
    """PRD 3.3: "For an `EBOOK` order, paying also delivers access immediately:
    `fulfillment_status` moves to `DELIVERED`, `access_start` is set to the current
    clock, and `access_end` is set to `access_start` plus `rental_term_days` days."

    Design: Corner/endpoints/ebook_pay_grants_access_window
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item(ebook_available=True)
    cust = create_funded_customer(50000, email="eb@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers), 201)
    paid = validate_success(api.pay_order(order["id"], headers), 200)
    assert paid["fulfillment_status"] == "DELIVERED"
    # access_start 2026-03-01 + 30 days = 2026-03-31
    assert paid["access_end"].startswith("2026-03-31"), paid["access_end"]


def test_pay_already_paid_order_returns_409(api):
    """PRD 3.3: "Paying for an order requires its `payment_status` to be `UNPAID`, else
    `ERR_ORDER_NOT_PAYABLE`."

    Design: Corner/state_machines/pay_already_paid_order_returns_409
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item(ebook_available=True)
    cust = create_funded_customer(50000, email="pp@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers), 201)
    validate_success(api.pay_order(order["id"], headers), 200)
    res = api.pay_order(order["id"], headers)
    validate_error(res, "ERR_ORDER_NOT_PAYABLE", expected_status=409)


def test_cancel_confirmed_order_returns_409(api):
    """PRD 3.3: "Cancelling an order is permitted only while its `fulfillment_status` is
    `PENDING`; a cancel attempted once the order is `CONFIRMED`, `DELIVERED`,
    `COMPLETED`, or already `CANCELLED` is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_confirmed_order_returns_409
    """
    ctx = setup_paid_confirmed_rental(email="cc@x.com")
    res = api.cancel_order(ctx["order"]["id"], ctx["headers"])
    validate_error(res, "ERR_ORDER_NOT_CANCELLABLE", expected_status=409)


def test_list_orders_pagination_envelope(api):
    """PRD 2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="lo@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90), headers), 201)
    res = api.list_orders(headers, params={"customer_id": cust["id"]})
    data, meta = validate_paginated(res)
    assert res.json()["response_type"] == "array"
    assert meta["total_count"] == 1, meta["total_count"]
    assert meta["has_more"] is False
