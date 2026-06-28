"""Auth header extraction and RBAC (PRD §2.1)."""
from functools import wraps
from flask import request, g
from errors import err

VALID_ROLES = {"AdminUnderwriter", "ContractAdmin", "ClaimsAdjuster", "RepairFacility", "Auditor"}


def authenticate():
    """Priority 1: X-User-Role present and recognized."""
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header")
    g.user_role = role
    g.user_id = request.headers.get("X-User-ID")


def require_roles(*allowed):
    """Decorator: authenticate then enforce role membership (priority 1 then 2)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return deco
