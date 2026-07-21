"""Role authorization, customer ownership, and authentication gating."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID,
    make_customer, make_product, make_variant, make_order, add_line,
    create_product_payload, TEST_USERS,
)
from test_helpers.test_users import make_customer_headers, make_role_headers

MERCH = TEST_USERS["merchandiser_headers"]


def test_customer_cannot_create_product(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_product_returns_403
    """
    cust = make_customer()
    resp = api.create_product(create_product_payload(name="X", brand="Y", concentration="EDT"),
                              make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_merchandiser_cannot_approve_return_role_before_existence(api):
    """PRD §2.8: "(2) role authorization, including the customer-ownership check
    (`ERR_UNAUTHORIZED`, or `ERR_NOT_ORDER_OWNER` for an owner mismatch); (3)
    existence of every referenced resource" — role authorization precedes the
    existence check, so an unauthorized role on a missing resource still yields
    `ERR_UNAUTHORIZED`.

    Design: Corner/rbac/merchandiser_cannot_approve_return_returns_403
    """
    resp = api.approve_return(NON_EXISTENT_UUID, MERCH)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_customer_cannot_place_another_customers_order(api):
    """PRD §2.1: "a `Customer` may only place, cancel, or return against an `Order`
    whose `customer_id` equals `X-User-ID`, and may only act on a `ReturnRequest`
    whose underlying order belongs to them; an ownership violation is rejected
    with `ERR_NOT_ORDER_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_place_others_order_returns_403
    """
    cust_a = make_customer()
    cust_b = make_customer()
    prod = make_product(concentration="EDT")
    var = make_variant(prod["id"], kind="DECANT", volume_ml=10, unit_price_cents=3500, on_hand_qty=5)
    order_b = make_order(cust_b["id"])
    add_line(order_b["id"], cust_b["id"], var["id"], 1)
    resp = api.place_order(order_b["id"], {"redeem_points": 0}, make_customer_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_OWNER, 403)


def test_unknown_role_is_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/customer_read_unauthenticated_returns_401
    """
    headers = make_role_headers("some-user", "Anonymous")
    resp = api.get_customer(NON_EXISTENT_UUID, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
