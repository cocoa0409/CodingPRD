"""Role-based access control, ownership, and authentication.

Peer-role denials (an operator role attempting another role's exclusive op), the
non-owner customer check, and the missing-auth-headers rejection.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    register_customer,
    create_estimating_work_order, create_awaiting_approval_order,
    current_version, factories,
    make_customer_headers,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


def test_intakeclerk_cannot_author_estimate(api):
    """PRD §2.1: "When an authenticated principal attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/intakeclerk_cannot_author_estimate
    """
    cust, wo, items = create_estimating_work_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=2)],
    )
    v = current_version(wo["id"])
    res = api.create_estimate(wo["id"], {"expected_work_order_version": v}, CLERK)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_shopmanager_cannot_approve_on_customer_behalf(api):
    """PRD §2.1: "When an authenticated principal attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/shopmanager_cannot_approve_on_customer_behalf
    """
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=1)],
    )
    v = current_version(wo["id"])
    res = api.approve_work_order(wo["id"], factories.approve_payload(v, 5000), MANAGER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_approve_other_customers_order(api):
    """PRD §2.1: "the customer-acting operations — approving an estimate, declining an
    estimate, requesting a revision, and filing a warranty claim — all require that
    `X-User-ID` equal the `customer_id` of the targeted work order. A customer acting on a
    work order they do not own is rejected with `ERR_NOT_OWNER`, and this ownership check
    applies to exactly those four operations."

    Design: Corner/rbac/customer_cannot_approve_other_customers_order
    """
    other = register_customer()  # customer B, not the owner
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=1)],
    )
    v = current_version(wo["id"])
    res = api.approve_work_order(
        wo["id"], factories.approve_payload(v, 5000), make_customer_headers(other["id"]))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the capacity in which they
    act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_work_orders(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
