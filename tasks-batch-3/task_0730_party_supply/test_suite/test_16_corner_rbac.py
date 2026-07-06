"""Corner queue — rbac section."""
from test_helpers import (
    validate_error, validate_success, api_client, ApiErrorId,
    build_user_headers, make_store_clerk_headers, make_customer_headers,
    make_delivery_driver_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, setup_draft_order,
)


def test_customer_cannot_create_sku_returns_forbidden():
    """PRD §2.1: "If the declared role is not permitted to invoke the
    target endpoint according to §4, the request is rejected with
    ERR_FORBIDDEN."
    PRD §2.1: "A StoreManager owns the catalog and physical inventory:
    creating SKUs, bundles, helium tanks, event packages, applying and
    removing clearance, restocking, and refilling helium tanks."

    Design: Corner/rbac/customer_cannot_create_sku
    """
    cust = create_customer()
    resp = api_client.create_sku(
        {"sku_code": "FORBIDDEN-01", "category": "DECOR",
         "unit_price_cents": 100},
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_delivery_driver_cannot_reserve_order_returns_forbidden():
    """PRD §2.1: "If the declared role is not permitted to invoke the
    target endpoint according to §4, the request is rejected with
    ERR_FORBIDDEN."
    PRD §2.1: "A DeliveryDriver is the delivery-only operator whose
    sole exclusive operation is confirming that an order has been
    delivered on the road."

    Design: Corner/rbac/delivery_driver_cannot_reserve_order
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_delivery_driver_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "Every request to the API must carry two headers:
    X-User-ID, which identifies the acting user, and X-User-Role, which
    declares the role under which the request is made. If either header
    is missing, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    # No auth headers at all.
    resp = api_client.create_sku(
        {"sku_code": "MISS-01", "category": "DECOR", "unit_price_cents": 100},
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unknown_role_returns_unknown_role():
    """PRD §2.1: "If X-User-Role is not one of the four declared role
    names, the request is rejected with ERR_UNKNOWN_ROLE."

    Design: Corner/rbac/unknown_role_returns_unknown_role
    """
    headers = build_user_headers("test-hacker-1", "Hacker")
    resp = api_client.create_sku(
        {"sku_code": "MISS-02", "category": "DECOR", "unit_price_cents": 100},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE)
