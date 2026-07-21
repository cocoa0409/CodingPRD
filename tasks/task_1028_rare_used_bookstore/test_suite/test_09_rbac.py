"""Role-based access control and user-context header validation."""
from test_helpers import (
    validate_error, create_patron_payload, TEST_USERS,
)
from test_helpers.fixtures import new_intake_lot, make_empty_sale_order

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def test_appraiser_cannot_confirm_sale_order(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/appraiser_cannot_confirm_sale_order
    """
    order = make_empty_sale_order(channel="SHOP")
    res = api.confirm_sale_order(order["id"], APPRAISER)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_storeclerk_cannot_settle_lot(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/storeclerk_cannot_settle_lot
    """
    lot = new_intake_lot(acquisition_channel="PURCHASE")
    res = api.settle_lot(lot["id"], CLERK)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of
    the roles defined below, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.create_patron(create_patron_payload(display_name="Ghost"), {})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)
