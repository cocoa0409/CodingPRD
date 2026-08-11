"""Order parallel state dimensions (payment x fulfillment) and delivery
completion bubble-up (PRD §3.6, §3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    assert_order,
    deliver_delivery,
    dispatch_delivery,
    get_first_order_line,
    place_and_pay_order,
    schedule_delivery,
    setup_account_job_product,
    setup_paid_order_with_delivery,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _setup_delivered_order(api):
    """Two-unit order at 5000 list: paid, dispatched, delivered."""
    account, _, job, product = setup_account_job_product(
        company_name="Par Co", credit_limit_cents=100_000_000,
        jurisdiction_code="NV-OPEN", jurisdiction_name="Nevada Open",
        job_name="Depot", sku="P-PAR", product_name="Gal", list_price_cents=5000)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 2}], headers=ASSOCIATE)
    delivery = schedule_delivery(order["id"], job["id"],
                                 window_start="2026-06-11T09:00:00Z",
                                 window_end="2026-06-11T10:00:00Z")
    dispatch_delivery(delivery["id"])
    deliver_delivery(delivery["id"])
    return account, job, order, delivery


def test_payment_does_not_advance_fulfillment(api):
    """PRD §3.6: "Payment moves the payment dimension `UNPAID` to `PAID` and
    may be taken by a `StoreAssociate` or the owning `Contractor`, provided
    the account is still `ACTIVE` ..." PRD §3.6: "A created order starts
    `UNPAID` and `PENDING` with `refunded_cents` zero and `paid_at` null; its
    creation recomputes the account's `outstanding_balance_cents` and
    increments the account's `version`."

    Payment mutates only the payment dimension: a freshly paid order is PAID
    while still PENDING on the fulfillment dimension.

    Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_dimensions
    """
    account, _, job, product = setup_account_job_product(
        company_name="Par Co", credit_limit_cents=100_000_000,
        jurisdiction_code="NV-OPEN", jurisdiction_name="Nevada Open",
        job_name="Depot", sku="P-PAR", product_name="Gal", list_price_cents=5000)
    order = place_and_pay_order(
        account["id"], job["id"],
        [{"product_id": product["id"], "quantity": 2}], headers=ASSOCIATE)
    assert_order(order)
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "PENDING", (
        f"payment must not advance fulfillment, got {order['fulfillment_status']}")
    assert order["paid_at"] is not None


def test_return_leaves_fulfillment_delivered_untouched(api):
    """PRD §3.7: "The refund event then drives the order's payment dimension:
    while cumulative `refunded_cents` stays below `total_cents`, a `PAID`
    order becomes `PARTIALLY_REFUNDED`; when `refunded_cents` reaches
    `total_cents` exactly, the order becomes `REFUNDED` — whether it arrived
    there from `PAID` or from `PARTIALLY_REFUNDED`." PRD §3.7: "There is no
    restocking fee: the refund is full merchandise plus tax on that
    merchandise."

    A one-unit return against the delivered two-unit order (unit price 5000,
    tax refund round_half_up(5000 * 0.0825) = 413) moves payment to
    PARTIALLY_REFUNDED with refunded_cents 5413 while fulfillment stays
    DELIVERED.

    Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_dimensions
    """
    account, job, order, delivery = _setup_delivered_order(api)
    mid = validate_success(api.get_order(order["id"], ASSOCIATE))
    assert mid["payment_status"] == "PAID"
    assert mid["fulfillment_status"] == "DELIVERED", (
        "dispatch and completion moved fulfillment PENDING -> OUT_FOR_DELIVERY "
        "-> DELIVERED without touching payment")
    line = get_first_order_line(order["id"])
    resp = api.return_order_line(line["id"], {"quantity": 1}, ASSOCIATE)
    validate_success(resp, expected_status=201)
    after = validate_success(api.get_order(order["id"], ASSOCIATE))
    assert after["payment_status"] == "PARTIALLY_REFUNDED", (
        f"partial refund must flip payment to PARTIALLY_REFUNDED, "
        f"got {after['payment_status']}")
    assert after["fulfillment_status"] == "DELIVERED", (
        f"a payment-side return leaves fulfillment untouched, "
        f"got {after['fulfillment_status']}")
    assert after["refunded_cents"] == 5413, (
        f"5000 merchandise + 413 tax = 5413, got {after['refunded_cents']}")


def test_mark_delivered_before_dispatch_rejected(api):
    """PRD §3.8: "Both completion and failure require the delivery to be in
    `EN_ROUTE`; attempting either from any other state is rejected with
    `ERR_DELIVERY_NOT_EN_ROUTE` (HTTP 409)."

    Design: Corner/state_machines/mark_delivered_before_dispatch_rejected
    """
    from test_helpers import ApiErrorId, validate_error
    account, job, product, order, delivery = setup_paid_order_with_delivery(
        window_start="2026-06-20T09:00:00Z", window_end="2026-06-20T10:00:00Z",
        jurisdiction_code="HI-OPEN")
    resp = api.mark_delivery_delivered(delivery["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_EN_ROUTE)
    after = validate_success(api.get_delivery(delivery["id"], MANAGER))
    assert after["status"] == "SCHEDULED", (
        f"the failed transition must not move the delivery, got {after['status']}")
