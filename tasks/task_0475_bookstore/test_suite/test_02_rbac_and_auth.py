"""Role-based access control and authentication checks."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers, build_user_headers,
    create_publisher_return_payload, create_sales_order_payload,
    make_member, make_title, receive_stock,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]


def test_member_cannot_reserve_inventory(api):
    """PRD §4 (endpoint authorization): `POST /sales-orders/{id}/reserve` is
    authorized for Bookseller, StoreAdmin only.
    PRD §2.1: "the system checks whether the acting role is permitted to perform
    the requested operation per the authorization table in §4; if it is not, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/member_cannot_reserve_inventory
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 1)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    resp = api.reserve_order(
        order["id"], {"expected_sales_order_version": order["version"]}, mh
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_bookseller_cannot_create_publisher_return(api):
    """PRD §4 (endpoint authorization): `POST /publisher-returns` is authorized
    for InventoryManager, StoreAdmin only.
    PRD §2.1: "the system checks whether the acting role is permitted to perform
    the requested operation per the authorization table in §4; if it is not, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/bookseller_cannot_create_publisher_return
    """
    title = make_title(list_price_cents=1000, returnable=True)
    resp = api.create_publisher_return(
        create_publisher_return_payload(title["id"], 1), BOOKSELLER
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "When either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    title = make_title(list_price_cents=1000)
    # No X-User-ID / X-User-Role headers at all.
    resp = api.get_title(title["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
