"""Authentication, authorization, and existence-resolution corner cases."""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, build_user_headers,
    onboard_member, create_member_payload, create_locker_payload,
    make_cellar_member_headers,
)

MGR = TEST_USERS["cellar_manager_headers"]


# --------------------------------------------------------------------------- #
# Queue B — entities / member_get_nonexistent_returns_not_found
# --------------------------------------------------------------------------- #
def test_member_get_nonexistent_returns_not_found(api):
    """PRD §2.9: "every id in the path and every foreign-key or reference in the body is
    resolved left-to-right, and the first that does not name an existing resource yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/member_get_nonexistent_returns_not_found
    """
    validate_error(api.get_member(NON_EXISTENT_UUID, MGR), ApiErrorId.ERR_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# Queue B — entities / member_read_unknown_role_returns_unauthenticated
# --------------------------------------------------------------------------- #
def test_member_read_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is
    not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/entities/member_read_unknown_role_returns_unauthenticated
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    validate_error(api.get_member(NON_EXISTENT_UUID, ghost), ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------- #
# Queue B — rbac / appraiser_create_locker_returns_unauthorized
# --------------------------------------------------------------------------- #
def test_appraiser_create_locker_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well formed but the role is not permitted to
    perform the requested operation — or a member attempts to act on a resource it does
    not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/appraiser_create_locker_returns_unauthorized
    """
    appraiser = build_user_headers("appraiser-alpha", "Appraiser")
    payload = create_locker_payload(size_tier="SMALL", climate_zone="RED", capacity_bottles=2)
    validate_error(api.create_locker(payload, appraiser), ApiErrorId.ERR_UNAUTHORIZED.value)


# --------------------------------------------------------------------------- #
# Queue B — rbac / member_create_by_member_returns_unauthorized
# --------------------------------------------------------------------------- #
def test_member_create_by_member_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well formed but the role is not permitted to
    perform the requested operation — or a member attempts to act on a resource it does
    not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_create_by_member_returns_unauthorized
    """
    existing = onboard_member(api, tier="STANDARD", activate=False)
    payload = create_member_payload(membership_tier="STANDARD")
    validate_error(
        api.create_member(payload, make_cellar_member_headers(existing["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
