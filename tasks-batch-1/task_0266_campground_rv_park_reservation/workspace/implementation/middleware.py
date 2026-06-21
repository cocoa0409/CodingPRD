"""Authentication and role extraction (PRD §2.1).

Every request must carry two headers:
  - X-User-ID:   the acting principal id (opaque for Operator; Guest.id for Guest)
  - X-User-Role: exactly "Operator" or "Guest"

Missing/malformed -> ERR_UNAUTHENTICATED (401).
"""
from flask import request

import errors

ROLE_OPERATOR = "Operator"
ROLE_GUEST = "Guest"
VALID_ROLES = {ROLE_OPERATOR, ROLE_GUEST}


def get_principal():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise errors.err(
            errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header"
        )
    return user_id.strip(), role


def require_role(role, allowed):
    """Authorization (PRD §2.8 step 2): role must be in the allowed set."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
