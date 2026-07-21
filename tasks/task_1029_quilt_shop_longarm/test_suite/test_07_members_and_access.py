"""Member creation defaults and validation, not-found handling, filtered cut listing, and the
Manager-only discontinue authorization boundary."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_bolt, create_cut,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Corner/entities/member_create_returns_defaults
# =========================================================================
def test_member_create_returns_defaults(api):
    """PRD §3.1: "A newly created member begins with a points_balance of zero and therefore a
    loyalty_tier of BRONZE". PRD §2.4: "an integer version that begins at 1 and increments by
    one on each mutation of the resource." A member created with name and email returns 201
    with points_balance 0, loyalty_tier BRONZE, and version 1.

    Design: Corner/entities/member_create_returns_defaults
    """
    resp = api.create_member({"name": "New M", "email": "new-defaults@example.com"}, CLERK)
    data = validate_success(resp, 201)
    assert data["points_balance"] == 0
    assert data["loyalty_tier"] == "BRONZE"
    assert data["version"] == 1


# =========================================================================
# Corner/entities/member_create_missing_required_email_returns_validation
# =========================================================================
def test_member_create_missing_email_rejected(api):
    """PRD §3.1: "A member record is opened by staff ... who supply the member's name, email,
    and optionally a phone number". PRD §2.5: "Required fields must be present and well-typed
    ... ERR_VALIDATION for a missing field, wrong type, or invalid enum member". Creating a
    member without the required email is rejected.

    Design: Corner/entities/member_create_missing_required_email_returns_validation
    """
    resp = api.create_member({"name": "No Email"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# =========================================================================
# Corner/entities/member_get_not_found_returns_404
# =========================================================================
def test_member_get_not_found(api):
    """PRD §2.5: "Every identifier referenced in the path or the request body ... must resolve
    to an existing row. References are checked left to right, and the first unresolved
    reference yields the corresponding not-found error (for example ERR_MEMBER_NOT_FOUND ...),
    each returned with HTTP 404." Fetching a member id that does not exist returns
    ERR_MEMBER_NOT_FOUND.

    Design: Corner/entities/member_get_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


# =========================================================================
# Corner/endpoints/list_fabric_cuts_filtered_by_bolt
# =========================================================================
def test_list_fabric_cuts_filtered_by_bolt(api):
    """PRD §3.2: "Cuts can be listed and filtered by bolt_id, by member_id, or by status."
    A bolt with two cuts returns both rows, and the pagination envelope reports total_count 2,
    when the list is filtered by that bolt_id.

    Design: Corner/endpoints/list_fabric_cuts_filtered_by_bolt
    """
    bolt = create_bolt(api, price_per_yard=3.00, original_yards=40, color="Slate")
    create_cut(api, bolt["id"], 2)
    create_cut(api, bolt["id"], 3)
    resp = api.list_fabric_cuts(CLERK, params={"bolt_id": bolt["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 cuts, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"


# =========================================================================
# Corner/rbac/discontinue_by_clerk_returns_forbidden
# =========================================================================
def test_discontinue_by_clerk_forbidden(api):
    """PRD §2.1: "A Manager can do everything a Clerk can do, and is additionally the only role
    permitted to discontinue a fabric bolt." PRD §2.1: "When the headers are valid but the role
    is not permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN." A Clerk discontinuing a bolt is rejected and the bolt stays IN_STOCK.

    Design: Corner/rbac/discontinue_by_clerk_returns_forbidden
    """
    bolt = create_bolt(api, price_per_yard=5.00, original_yards=15, color="Plum")
    resp = api.discontinue_fabric_bolt(bolt["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    after = validate_success(api.get_fabric_bolt(bolt["id"], CLERK), 200)
    assert after["status"] == "IN_STOCK"
