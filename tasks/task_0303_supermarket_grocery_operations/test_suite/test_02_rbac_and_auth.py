"""Role-based access control and user-context header validation.

All tests translate corner-design instances (queue B): the rbac and validations
sections.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    fixtures,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]


def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one of the roles defined below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_unauthenticated
    """
    bad_headers = {"X-User-ID": "x-1", "X-User-Role": "NotARole",
                   "Content-Type": "application/json"}
    resp = api.create_department({"code": "X", "name": "X"}, bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_cashier_cannot_create_department(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "A `StoreManager` creates a department by supplying a `code`, a human-readable `name`, and optionally a `shrink_alert_bps` threshold."

    Design: Corner/rbac/cashier_cannot_create_department
    """
    resp = api.create_department({"code": "GROCERY", "name": "Grocery"}, CSH)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_receiving_clerk_cannot_create_promotion(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.5: "A `PriceManager` (or `StoreManager`) drives the weekly ad."

    Design: Corner/rbac/receiving_clerk_cannot_create_promotion
    """
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="RB",
                                      unit_price_cents=200, reorder_point_qty=0)
    resp = api.create_promotion(
        {"product_id": product["id"], "promo_type": "PERCENT_OFF",
         "percent_off_bps": 1000, "min_qty": 1, "stackable": False,
         "effective_start": "2026-06-01T00:00:00Z",
         "effective_end": "2026-06-30T00:00:00Z"}, RC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_member_cannot_clip_on_another_members_account(api):
    """PRD §2.1: "A `LoyaltyMember` may clip a coupon only onto its own account ...
    an attempt to act on another member's resources is rejected with
    `ERR_UNAUTHORIZED`."
    PRD §2.10: "for an entity-backed `LoyaltyMember`, ownership matching `X-User-ID`
    to the resource's member foreign key — else `ERR_UNAUTHORIZED`"

    Design: Corner/rbac/member_cannot_clip_on_another_members_account
    """
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Own",
                                      unit_price_cents=99, reorder_point_qty=0)
    coupon = fixtures.create_coupon(product["id"], code="OWN5", discount_cents=50)
    owner = fixtures.create_member(email="owner@x.com")
    other = fixtures.create_member(email="other@x.com")
    # The acting member (other) does not own the owner's account.
    other_headers = build_user_headers(other["id"], "LoyaltyMember")
    resp = api.clip_coupon(owner["id"], {"coupon_id": coupon["id"]}, other_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
