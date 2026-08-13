"""Auth middleware (PRD §2.1) and role authorization helpers (pipeline stages 1 and 3)."""
from flask import g, request

from errors import ApiError

ROLES = (
    "ModelOwner",
    "ModelValidator",
    "ModelRiskOfficer",
    "RegulatoryReporter",
    "PlatformAdmin",
)
BUSINESS_ROLES = (
    "ModelOwner",
    "ModelValidator",
    "ModelRiskOfficer",
    "RegulatoryReporter",
)


def authenticate():
    """Pipeline stage 1: header context. Runs before every request."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and X-User-Role "
            "must name a declared role",
        )
    g.user_id = user_id
    g.user_role = role


def require_roles(*roles):
    """Pipeline stage 3: role authorization."""
    if g.user_role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            403,
            "Role '%s' is not authorized for this endpoint" % g.user_role,
        )
