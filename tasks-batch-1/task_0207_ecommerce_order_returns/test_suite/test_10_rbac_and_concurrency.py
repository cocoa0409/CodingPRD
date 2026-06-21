"""RBAC, authentication, generic validation, and optimistic concurrency
(PRD §2.1 / §2.6 / §2.9).

Corner queue: rbac (role denied, ownership denied, missing auth), errors (generic
ERR_VALIDATION), cross_cutting (OCC stale order/return version).
"""
from test_helpers import (
    fixtures as fx,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    create_order_payload,
    checkout_payload,
    approve_return_payload,
)

DELIVER_CLOCK = "2026-06-05T00:00:00Z"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_warehouse_operator_cannot_capture_payment(api):
    """PRD §2.1: "When an authenticated principal attempts an operation their role is
    not permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP
    403)."

    Design: Corner/rbac/warehouse_operator_cannot_capture_payment_forbidden
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    resp = api.capture_payment(ctx["order"]["id"], fx.OP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_cancel_another_customers_return(api):
    """PRD §2.1: "A Customer may act only on carts, orders, and returns they own —
    attempting to check out, add lines to, open a return against, or cancel a return
    for a resource whose customer_id does not equal the caller's X-User-ID is rejected
    with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_return_not_owner
    """
    fx.set_clock(DELIVER_CLOCK)
    cust_b = fx.create_customer()  # a different customer who will attempt the cancel
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    # Customer B (not the owner) tries to cancel customer A's RMA.
    resp = api.cancel_return(rma["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of these
    four known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    customer = fx.create_customer()
    # No X-User-ID / X-User-Role headers at all → missing auth context.
    resp = api.create_order(create_order_payload(customer["id"]),
                            {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Generic validation
# ---------------------------------------------------------------------------
def test_negative_promo_returns_generic_validation(api):
    """PRD §2.9: "A generic business-rule violation not covered by a more specific
    code — such as a negative promo_flat_cents or a quantity below one — is reported
    as ERR_VALIDATION (HTTP 422)."

    Design: Corner/errors/error_validation_generic_negative_promo
    """
    customer = fx.create_customer()
    headers = make_customer_headers(customer["id"])
    resp = api.create_order(
        create_order_payload(customer["id"], promo_flat_cents=-100), headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------
def test_stale_order_version_on_checkout_rejected(api):
    """PRD §2.6: "a checkout request must carry expected_order_version, and the value
    must match the target Order's current version. If a line was added or removed
    since the client last read the cart — each such mutation increments Order.version
    and changes the totals the client is about to authorize — the client's view is
    stale and the checkout is rejected with ERR_STALE_ORDER_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_checkout_returns_412
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], warehouse["id"], 10)

    order = fx.create_cart(customer["id"])
    v0 = order["version"]  # version BEFORE adding a line
    fx.add_line(order["id"], customer["id"], product["id"], 1)  # bumps version

    headers = make_customer_headers(customer["id"])
    resp = api.checkout_order(order["id"], checkout_payload(v0), headers)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)


def test_stale_return_version_on_approve_rejected(api):
    """PRD §2.6: "an approve request must carry expected_return_version, and the value
    must match the target ReturnAuthorization's current version. If another operator
    has already approved or otherwise mutated the RMA — advancing its version and
    locking a settlement figure — the approver's view is stale and the request is
    rejected with ERR_STALE_RETURN_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_return_version_on_approve_returns_412
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    stale_version = rma["version"] - 1
    resp = api.approve_return(
        rma["id"], approve_return_payload(stale_version), fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_RETURN_VERSION.value)
