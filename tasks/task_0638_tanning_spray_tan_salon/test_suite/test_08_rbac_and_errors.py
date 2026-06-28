"""Role-based access control and not-found existence errors.

Covers queue-B rbac and errors corner instances.
"""
from test_helpers import (
    ApiErrorId,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    create_membership_plan_payload,
    create_member_payload,
)
from test_helpers import fixtures as fx

SALON_MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_member_cannot_freeze_other_member(api):
    """PRD §2.1: "A `Member` may therefore freeze, unfreeze, upgrade, or cancel only
    its own membership, book or cancel only its own sessions, and place retail orders
    only under its own member id; any cross-member attempt yields `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_freeze_other_member
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=0)
    fx.set_clock("2026-06-01T00:00:00Z")
    member_a = fx.create_active_member(plan["id"], full_name="Member A")
    member_b = fx.create_active_member(plan["id"], full_name="Member B")
    # Member A (X-User-ID = A) attempts to freeze member B.
    resp = api.freeze_member(
        member_b["id"], {"expected_member_version": member_b["version"]},
        make_member_headers(member_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_front_desk_cannot_create_plan(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation — or a `Member` attempts to act on a membership
    that is not its own — the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/front_desk_cannot_create_plan
    """
    resp = api.create_membership_plan(
        create_membership_plan_payload(tier_code="BASIC", monthly_fee_cents=3000,
                                       weekly_uv_session_cap=0),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the operational
    capacity in which that principal acts. ... If either header is missing or
    malformed, the request is rejected with `ERR_MISSING_AUTH_HEADERS`."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api.list_membership_plans({})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, expected_status=401)


def test_plan_not_found_on_member_create(api):
    """PRD §2.7: "For any request that names resources in its path or body, the
    server validates existence left to right ... The first identifier that does not
    resolve produces the corresponding not-found error — `ERR_MEMBER_NOT_FOUND`,
    `ERR_EQUIPMENT_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND` — before
    any deeper validation runs."

    Design: Corner/errors/plan_not_found_on_member_create
    """
    resp = api.create_member(
        create_member_payload(full_name="No Plan", plan_id=NON_EXISTENT_UUID), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value, expected_status=404)
