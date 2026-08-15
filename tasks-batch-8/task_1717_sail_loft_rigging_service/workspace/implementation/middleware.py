"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

import errors

VALID_ROLES = {"Customer", "Sailmaker", "Measurer", "Rigger", "LoftManager"}


def get_auth():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT if absent/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.missing_context()
    if not role or role not in VALID_ROLES:
        raise errors.missing_context()
    return user_id, role


def require_roles(*allowed):
    """Check headers present (400) then role allowed (403). Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.forbidden_role(
            f"Role {role} is not permitted for this endpoint; allowed: {', '.join(allowed)}"
        )
    return user_id, role


def require_owner(user_id, customer_id, msg="Acting Customer does not own this resource"):
    """Ownership check for Customer-role callers."""
    if user_id != customer_id:
        raise errors.forbidden_role(msg)
