"""Authentication and role-based access control (PRD 2.1)."""

from flask import g, request

from errors import ApiError

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ROLE_ADMIN = "DataPlatformAdmin"
ROLE_ENGINEER = "DataEngineer"
ROLE_STEWARD = "IdentitySteward"
ROLE_PRIVACY = "PrivacyOfficer"
ROLE_ANALYST = "SegmentAnalyst"
ROLE_GOVERNANCE = "DataGovernanceOfficer"
ROLE_DESTINATION = "DestinationPlatform"

ALL_ROLES = (
    ROLE_ADMIN,
    ROLE_ENGINEER,
    ROLE_STEWARD,
    ROLE_PRIVACY,
    ROLE_ANALYST,
    ROLE_GOVERNANCE,
    ROLE_DESTINATION,
)

# Every GET endpoint except the segment performance and overlap reads.
READ_ROLES = ALL_ROLES
REPORT_ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_GOVERNANCE)


def load_actor():
    """Validation rung 1: both identity headers present and non-blank."""
    user_id = request.headers.get(HEADER_USER_ID)
    user_role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_role is None:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if not user_id.strip() or not user_role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    g.user_id = user_id.strip()
    g.user_role = user_role.strip()


def require_role(*roles):
    """Validation rung 2: the role is recognised and authorized for the endpoint."""
    role = getattr(g, "user_role", None)
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    if roles and role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return g.user_id, role


def actor_id():
    return g.user_id


def actor_role():
    return g.user_role


def require_destination_actor(destination_id):
    """Validation rung 3: an acting DestinationPlatform must be the named destination."""
    if getattr(g, "user_role", None) != ROLE_DESTINATION:
        return
    if g.user_id != destination_id:
        raise ApiError("ERR_DESTINATION_ACTOR_MISMATCH")
