"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2)."""
from flask import request

from errors import err

VALID_ROLES = {"Host", "Guest", "PlatformAdmin", "Anonymous"}


def get_principal():
    """Extract (user_id, role) from headers. Returns (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allowed_roles):
    """Validate auth headers and role authorization.

    Priority 1: headers present and well-formed -> else ERR_UNAUTHENTICATED (401).
    Priority 2: role permitted for the operation -> else ERR_FORBIDDEN_ROLE (403).

    Returns (user_id, role) for the authenticated caller.
    """
    user_id, role = get_principal()
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or malformed auth headers")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "role not permitted for this operation")
    return user_id, role
