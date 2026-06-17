"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.7)."""
from flask import request
from errors import err

KNOWN_ROLES = {"Anonymous", "Customer", "ShopStaff", "ShopManager"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns Caller or raises
    ERR_UNAUTHENTICATED. Used on all endpoints except the two bootstrap ops."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """Raise ERR_FORBIDDEN if caller.role not in allowed_roles."""
    if caller.role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
