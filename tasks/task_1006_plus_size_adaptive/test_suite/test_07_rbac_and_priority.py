"""RBAC enforcement and a checkout validation-precedence pair.

Queue A (Difficulty): checkout_state_beats_insufficient_points.
Queue B (Corner): customer-cannot-create-product, cross-customer checkout denial,
anonymous-cannot-create-order.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers, make_anonymous_headers,
    register_customer, checkout,
    setup_order_with_line,
    create_product_payload,
)

SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# checkout_state_beats_insufficient_points (Queue A)
# ---------------------------------------------------------------------------
def test_recheckout_reports_invalid_state_over_insufficient_points(api):
    """PRD §2.9: "when a single request could fail several checks, the checks are
    evaluated in a fixed priority order, and the first failure encountered determines
    the error returned."
    PRD §2.9: "(5) state — the target must be in a state that permits the requested
    transition, else `ERR_INVALID_STATE` (409)".

    Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_insufficient_points
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])  # PENDING -> AUTHORIZED
    resp = api.checkout_order(
        ctx["order"]["id"], {"loyalty_redeem_points": 100},
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_failed_recheckout_leaves_payment_authorized(api):
    """PRD §3.3: "Checkout authorizes the order, advancing `payment_status` from
    `PENDING` to `AUTHORIZED`."

    Design: Difficulty/priority_pair_validation_conflict/checkout_state_beats_insufficient_points
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"])
    api.checkout_order(
        ctx["order"]["id"], {"loyalty_redeem_points": 100},
        make_customer_headers(ctx["customer"]["id"]),
    )
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["payment_status"] == "AUTHORIZED"


# ---------------------------------------------------------------------------
# Corner: RBAC
# ---------------------------------------------------------------------------
def test_customer_cannot_create_product(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform
    the requested operation — or whose principal fails an ownership check described
    below — is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_product
    """
    customer = register_customer(api)
    resp = api.create_product(
        create_product_payload(name="Sneaky", category="TOPS", base_price_cents=1000),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_customer_cannot_checkout_another_customers_order(api):
    """PRD §2.1: "A `Customer` may act only on their own orders, order lines, returns,
    appointments, subscriptions, and box shipments."

    Design: Corner/rbac/customer_cannot_checkout_another_customers_order
    """
    ctx = setup_order_with_line(api, variant_overrides={"inventory_on_hand": 10})
    intruder = register_customer(api)
    resp = api.checkout_order(
        ctx["order"]["id"], {}, make_customer_headers(intruder["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    order = validate_success(api.get_order(ctx["order"]["id"], SM))
    assert order["payment_status"] == "PENDING"


def test_anonymous_cannot_create_order(api):
    """PRD §2.1: "Two operations are open to `Anonymous`: registering a new customer,
    and read-only browsing of the catalog (product listings, individual products, a
    product's variants, and individual variants)."

    Design: Corner/rbac/anonymous_cannot_create_order
    """
    resp = api.create_order(make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
