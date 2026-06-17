"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request
from errors import err

VALID_ROLES = {"ShopAdmin", "ShopManager", "Designer", "Customer", "Installer"}


def get_user_context():
    """Validate auth headers. Returns (user_id, role) or raises ERR_MISSING_OR_INVALID_USER_CONTEXT."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                  "Missing or invalid X-User-ID/X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_FOR_ROLE if role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this operation" % role)
