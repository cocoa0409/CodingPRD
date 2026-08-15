"""Auth header extraction and role checking.

Headers (PRD §2.1): X-User-ID and X-User-Role on every request.
X-User-ID is an opaque operator identifier for every role — never compared
to any entity id (it IS recorded on drafted responses for segregation of
duties).
"""
from flask import g, request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE

ROLES = {
    "PlatformAdmin",
    "ClaimsAnalyst",
    "TpaAgent",
    "AgencyLiaison",
    "ChargeAuditor",
    "RatingAnalyst",
    "TpaManager",
}


def authenticate():
    """Runs before every API request. Populates g.user_id / g.user_role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "missing or unrecognized X-User-ID / X-User-Role",
        )
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    if g.user_role not in roles:
        raise err(ERR_FORBIDDEN_ROLE, 403, "caller role is not listed for this endpoint")
