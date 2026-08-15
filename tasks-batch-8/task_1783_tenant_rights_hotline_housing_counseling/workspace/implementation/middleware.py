"""Auth header extraction and role checking.

Headers: X-User-Role (required, must be a declared role) and X-User-ID
(required for every role except Anonymous).
"""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


ROLES = {
    "Anonymous",
    "Caller",
    "Counselor",
    "HotlineSupervisor",
    "DataProtectionOfficer",
    "AgencyAdmin",
    "Analyst",
}


def actor():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED on bad headers."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or invalid X-User-Role header")
    user_id = request.headers.get("X-User-ID")
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise_err(ERR_UNAUTHENTICATED, "missing X-User-ID header")
    return role, user_id


def require_roles(*roles):
    """Authenticate, then enforce endpoint-level role admission."""
    role, user_id = actor()
    if role not in roles:
        raise_err(ERR_FORBIDDEN, "role %s is not permitted for this endpoint" % role)
    return role, user_id
