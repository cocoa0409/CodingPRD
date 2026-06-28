"""Auth header extraction and RBAC checks (PRD §2.1, §3.10)."""
from flask import request

import errors
from errors import err

ROLES = {"Homeowner", "Coordinator", "Electrician", "UtilityReviewer", "Anonymous"}


def get_identity():
    """Return (user_id, role) from headers, or (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allowed_roles):
    """Authenticate then authorize.

    Priority 1: X-User-ID and X-User-Role headers must both be present
                (ERR_UNAUTHENTICATED, 401).
    Priority 2: the declared role must be permitted for this operation
                (ERR_FORBIDDEN_ROLE, 403).

    Returns (user_id, role).
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "missing or invalid auth headers")
    if role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN_ROLE, "role not permitted for this operation")
    return user_id, role
