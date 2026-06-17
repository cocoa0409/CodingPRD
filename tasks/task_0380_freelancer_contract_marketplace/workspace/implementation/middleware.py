"""Auth header extraction and RBAC (PRD 2.1, 2.6)."""
from flask import request

from errors import err

VALID_ROLES = {"Client", "Freelancer", "Arbitrator", "PlatformAdmin"}


def require_auth():
    """Validate the two mandatory user-context headers (PRD 2.1).

    Returns (user_id, role). Missing or malformed -> ERR_MISSING_USER_CONTEXT.
    "Malformed" includes an unrecognized role value.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Authorization: the role must be permitted for this operation (PRD 2.6).

    Ownership checks (entity-backed identity owning the resource) are applied
    separately within each handler after existence is established.
    """
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
