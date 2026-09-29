"""Band 1 of the rejection ladder: authentication and endpoint authorization.

PRD 2.1 / 2.8: header presence, then role recognition, then endpoint
permission -- and the permission decision is made BEFORE any identifier in the
URL is resolved, so an unauthorized caller addressing a missing resource sees
403 rather than 404.
"""
from flask import g, request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "ProgramManager",
    "ComplianceOfficer",
    "Tester",
    "RemediationOwner",
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authorize(*allowed_roles):
    """Run band 1.  Stores the caller identity on flask.g."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id.strip()
    g.role = role
    return g.user_id, role


def require_role(*allowed_roles):
    """Action-level role reservation (e.g. TERMINATE is a ComplianceOfficer act)."""
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
