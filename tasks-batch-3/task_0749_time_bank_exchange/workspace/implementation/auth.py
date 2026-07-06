"""Auth middleware — extract X-User-ID / X-User-Role and enforce role gate."""
from flask import request
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_ROLE_NOT_PERMITTED

ROLE_ANON = "Anonymous"
ROLE_MEMBER = "Member"
ROLE_ORGANIZER = "ProjectOrganizer"
ROLE_ADMIN = "PlatformAdmin"

ALL_ROLES = {ROLE_ANON, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN}


def get_headers():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if either missing / malformed.
    Note the caller can accept Anonymous by NOT calling this helper (allowed_roles
    check happens after). But per PRD, both headers must be present and syntactically
    valid except on POST /_clock/set_current_utc and Anonymous endpoints."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise_err(ERR_UNAUTHENTICATED, "Malformed auth headers")
    if role not in ALL_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Unknown role value")
    return user_id, role


def require_role(allowed_roles):
    """Validate headers + enforce role allow-list. Returns (user_id, role).

    If ROLE_ANON is in allowed_roles, missing headers are permitted; but if a
    caller supplies a role, it must be one of allowed_roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if role is None and user_id is None:
        # No headers — only OK if Anonymous is in allowed_roles.
        if ROLE_ANON in allowed_roles:
            return None, ROLE_ANON
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")

    # Header presence + syntax check.
    if not user_id or not role or not isinstance(user_id, str) or not isinstance(role, str):
        raise_err(ERR_UNAUTHENTICATED, "Missing / malformed auth headers")
    if role not in ALL_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Unknown role value")

    # Role allow-list.
    if role not in allowed_roles:
        raise_err(ERR_ROLE_NOT_PERMITTED, f"Role {role} not permitted on this endpoint")

    return user_id, role
