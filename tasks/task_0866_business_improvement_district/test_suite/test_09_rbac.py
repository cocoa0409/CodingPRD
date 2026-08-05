"""Role-based access control: authentication, authorization (SoD between preparer and
board), and entity-backed resource ownership."""
from test_helpers import (
    validate_error,
    ApiErrorId, build_user_headers,
    create_bid_payload,
    setup_draft_budget_with_lines, setup_two_equal_parcels_adopted,
    find_assessment, account_for,
    make_property_owner_headers,
    TEST_USERS,
)

BOARD = TEST_USERS["board_member_headers"]


def test_unknown_role_rejected_as_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of the five roles
    defined below, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/unauthenticated_unknown_role_rejected
    """
    headers = build_user_headers("nobody", "Anonymous")
    resp = api.create_bid(create_bid_payload(name="NoAuth"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_board_member_cannot_propose_budget(api):
    """PRD §2.1: "A BoardMember may not prepare or propose budgets".
    PRD §2.1: "If the role is recognized but is not permitted to invoke the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/boardmember_cannot_propose_budget
    """
    ctx = setup_draft_budget_with_lines([("CLEAN", 4025000)], total_expenditure=4025000, with_parcel=True)
    resp = api.propose_budget(ctx["budget"]["id"], BOARD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_owner_paying_foreign_account_rejected(api):
    """PRD §2.1: "ownership checks on any resource that traces back to a parcel — a payment
    on a collection account ... compare the resource's owning parcel to X-User-ID ... A
    mismatch between an entity-backed principal and the resource it is trying to act on
    yields ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/not_resource_owner_payment_rejected
    """
    ctx = setup_two_equal_parcels_adopted()
    assessment_b = find_assessment(ctx["pb"]["id"], ctx["fy"]["id"])
    account_b = account_for(assessment_b["id"])
    owner_a = make_property_owner_headers(ctx["pa"]["id"])
    resp = api.create_payment(account_b["id"], {"amount_cents": 1000000}, owner_a)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
