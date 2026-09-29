"""Authentication, role authorization and state-scope enforcement (PRD 2.1)."""

from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "StateAdoptionOfficer",
    "ReviewCommitteeMember",
    "PublisherEditor",
    "EditorialDirector",
    "PricingManager",
    "SalesRep",
    "PublicCommenter",
)

ALL_ROLES = set(ROLES)


def authenticate():
    """Priority 1: both headers present and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a declared X-User-Role are required.")
    return user_id, role


def authorize(allowed_roles):
    """Priority 1 then priority 2."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation." % role,
        )
    return user_id, role


def check_state_scope(role, user_id, state_id):
    """Priority 16: a StateAdoptionOfficer may only act inside its own state."""
    if role == "StateAdoptionOfficer" and user_id != state_id:
        fail(
            "ERR_STATE_SCOPE_VIOLATION",
            "This officer does not serve the addressed state.",
        )
