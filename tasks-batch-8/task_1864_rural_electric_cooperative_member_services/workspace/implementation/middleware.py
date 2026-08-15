"""Auth: X-User-ID / X-User-Role header extraction and role gating per PRD §2.1."""
from flask import request, g

from errors import ApiError

ROLES = [
    "PlatformAdmin",
    "MemberServicesRep",
    "BoardDirector",
    "BoardSecretary",
    "RateAnalyst",
    "BillingClerk",
    "FieldOpsCoordinator",
    "Dispatcher",
    "LegalCounsel",
    "Member",
]


def get_context():
    """Validate the two auth headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-Role header missing or not a declared role")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    """Check that the authenticated role is in the allowed list."""
    role = getattr(g, "user_role", None)
    if role is None:
        get_context()
        role = g.user_role
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted on this endpoint" % role)


def require_member_ownership(resource_member_id):
    """For entity-backed Member role: check that X-User-ID matches the owning member's id."""
    uid = getattr(g, "user_id", None)
    role = getattr(g, "user_role", None)
    if role == "Member":
        if not uid or uid != resource_member_id:
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Member acting on a resource they do not own")


def get_json_body():
    """Parse and return the request JSON body. Raises ERR_INVALID_REQUEST on missing body."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    return body
