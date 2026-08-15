"""Authentication, authorization, and customer ownership scoping (PRD §2.1, §2.8, §4)."""
import pytest
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID,
    setup_book, create_draft_order, submit_site_check, file_report,
    get_only_application, create_jurisdiction_payload, make_customer_headers,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside this
    list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "Every request is validated in a fixed order, and a failure at any stage
    masks every later check: 1. **Authentication** — both headers present and the role
    declared (`ERR_UNAUTHENTICATED`)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    # Authentication precedes even the not-found check on a non-existent id.
    res = api.get_order(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_customer_cannot_create_jurisdiction(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the create-jurisdiction endpoint lists only PermitCoordinator.

    Design: Corner/rbac/customer_cannot_create_jurisdiction
    """
    customer = make_customer_headers("11111111-2222-4333-8444-555555555555")
    res = api.create_jurisdiction(
        create_jurisdiction_payload(
            name="Rogue County", county_name="Rogue", permit_threshold_sqft=200,
            anchoring_required=False, permit_base_fee_cents=10000,
            permit_per_sqft_cents=25, tax_rate_bp=600,
        ),
        customer,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_salesrep_cannot_decide_permit(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the permit approve endpoint lists only PermitCoordinator.

    Design: Corner/rbac/salesrep_cannot_decide_permit
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"])
    asm = submit_site_check(order["id"])
    file_report(asm["id"])
    app = get_only_application(order["id"])
    assert app["status"] == "SUBMITTED"
    res = api.approve_permit_application(app["id"], SALES)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    refreshed = api.get_permit_application(app["id"], PERMIT)
    assert refreshed.json()["data"]["status"] == "SUBMITTED", "rejected decision changes nothing"


def test_customer_cannot_read_others_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, the `X-User-ID` value is the `id` of
    the acting `Customer` record; ownership checks on any resource trace through the
    parent order, comparing the order's `customer_id` to `X-User-ID`, and a mismatch is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_read_others_order
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    stranger = make_customer_headers("99999999-8888-4777-8666-555555555555")
    res = api.get_order(order["id"], stranger)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
