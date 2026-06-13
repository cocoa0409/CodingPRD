"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.8; scaffold §1.7)."""
from flask import request

from errors import err

VALID_ROLES = {"PharmacyAdmin", "Pharmacist", "Technician", "Cashier"}


def get_actor():
    """Validate X-User-ID / X-User-Role headers (priority 1).

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT (401) when either
    header is absent or malformed (empty / unrecognized role value).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (priority 2). Raises ERR_INSUFFICIENT_PERMISSIONS (403)."""
    if role not in allowed:
        raise err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role '%s' may not perform this operation" % role,
        )
