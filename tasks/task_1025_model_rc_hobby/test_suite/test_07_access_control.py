"""Access control and listing: missing auth, role denial, hierarchical override
limits, and the orders pagination envelope."""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, ANONYMOUS_HEADERS,
    create_product_payload, create_campaign_payload, order_line,
    make_customer, make_product, make_order, make_customer_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# cn_missing_auth_header_returns_401
# ---------------------------------------------------------------------------
def test_request_without_auth_headers_rejected(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognised roles, the request is rejected with `ERR_MISSING_AUTH`
    (HTTP 401)."

    Design: Corner/rbac/cn_missing_auth_header_returns_401
    """
    resp = api.get_customer(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ---------------------------------------------------------------------------
# cn_rbac_product_create_customer_forbidden
# ---------------------------------------------------------------------------
def test_customer_cannot_create_product(api):
    """PRD 2.1: "When a request is authenticated but the role is not permitted
    to perform the requested operation — or a `Customer` attempts to act on a
    resource they do not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/cn_rbac_product_create_customer_forbidden
    """
    cust = make_customer(api)
    payload = create_product_payload(sku="X", name="X", product_type="PART",
                                     price_cents=1000, stock_on_hand=1)
    resp = api.create_product(payload, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# cn_rbac_campaign_cancel_staff_forbidden
# ---------------------------------------------------------------------------
def test_staff_cannot_cancel_campaign(api):
    """PRD 2.1: "A `StoreManager` is a hierarchical superset of `StoreStaff`:
    everything a `StoreStaff` can do, a `StoreManager` can do as well, plus the
    exclusive authority to cancel a pre-order campaign."

    Design: Corner/rbac/cn_rbac_campaign_cancel_staff_forbidden
    """
    prod = make_product(api, product_type="RC_VEHICLE", price_cents=10000, stock_on_hand=10)
    camp = get_success_data(api.create_campaign(create_campaign_payload(
        product_id=prod["id"], total_allocation_units=5, unit_price_cents=10000), STAFF))
    resp = api.cancel_campaign(camp["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# cn_orders_list_pagination_envelope
# ---------------------------------------------------------------------------
def test_orders_list_returns_paginated_envelope(api):
    """PRD 2.3: "Each list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/endpoints/cn_orders_list_pagination_envelope
    """
    cust = make_customer(api)
    prod = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=5)
    order = make_order(api, cust["id"], [order_line(prod["id"], 1, 10000)])
    resp = api.list_orders(STAFF, params={"customer_id": cust["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    ids = [o["id"] for o in data]
    assert order["id"] in ids
    assert "total_count" in meta
    assert "has_more" in meta
