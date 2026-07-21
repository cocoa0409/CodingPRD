"""Role-based access control: role authorization, ownership, and authentication."""
import pytest
from test_helpers import (
    validate_error, ApiErrorId,
    create_member, create_bottle, create_order, pay_order,
    setup_bottle_order_created, make_customer_headers,
)


# ── Corner: rbac / customer_cannot_fulfill_returns_unauthorized ──

def test_customer_calling_fulfill_returns_unauthorized(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_fulfill_returns_unauthorized
    """
    member, product, order = setup_bottle_order_created(api, unit_price_cents=2000)
    order = pay_order(api, member, order)
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]},
                             make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ── Corner: rbac / customer_cannot_read_others_order_returns_forbidden ──

def test_customer_reading_another_members_order_forbidden(api):
    """PRD §2.1: "A `Customer` who attempts to read or mutate a resource they do not own is
    rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_read_others_order_returns_forbidden
    """
    member_a = create_member(api)
    member_b = create_member(api)
    product = create_bottle(api, unit_price_cents=2000)
    order = create_order(api, member_a, [{"line_type": "UNIT", "product_id": product["id"],
                                          "quantity": 1}])
    resp = api.get_order(order["id"], make_customer_headers(member_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)


# ── Corner: rbac / missing_auth_headers_returns_unauthenticated ──

def test_request_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either
    header is missing, or `X-User-Role` is not one of the recognized roles, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.get_fusti("00000000-0000-0000-0000-000000000000", {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
