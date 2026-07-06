"""Authentication header and role-based access control denials."""
from test_helpers import (
    validate_error, ApiErrorId,
    create_customer, create_product_with_lot,
    create_order_with_line, submit_order, create_framing_order,
    make_customer_headers,
    create_product_payload,
)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two headers: X-User-ID, identifying
    the acting principal, and X-User-Role, naming that principal's role. If either
    header is missing or invalid, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    resp = api.create_product(
        create_product_payload(sku="X", name="X", sell_mode="UNIT", unit_price_cents=100),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_create_product_by_customer_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

    Design: Corner/validations/create_product_wrong_role_forbidden
    """
    customer = create_customer()
    resp = api.create_product(
        create_product_payload(sku="P1", name="Glue", sell_mode="UNIT", unit_price_cents=100),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_framing_start_by_customer_forbidden(api):
    """PRD §3.7: "A framing specialist then starts production, moving APPROVED to
    IN_PRODUCTION"
    PRD §2.1: "If the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

    Design: Corner/rbac/framing_start_by_customer_forbidden
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=100)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order["id"], customer["id"])
    framing = create_framing_order(order["id"], customer["id"], width_in=10, height_in=10)
    api.approve_framing(framing["id"], make_customer_headers(customer["id"]))
    resp = api.start_framing(framing["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
