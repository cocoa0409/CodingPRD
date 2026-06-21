"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 / §1.7).

Auth headers (PRD §2.1):
  X-User-ID    -- opaque operator identifier, required on every endpoint.
  X-User-Role  -- one of InventoryManager, PurchasingAgent, BarManager.

Required on ALL endpoints including GET. Missing/unknown -> ERR_UNAUTHENTICATED (401).
Role not permitted for the operation -> ERR_UNAUTHORIZED (403).
X-User-ID is never compared to any entity id (authorization is role-only).
"""
from functools import wraps

from flask import request

from errors import unauthenticated, unauthorized

ROLES = {"InventoryManager", "PurchasingAgent", "BarManager"}


def authenticate():
    """Validate the two mandatory headers. Returns the role string.
    Raises ERR_UNAUTHENTICATED on missing/unknown header."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "":
        raise unauthenticated("X-User-ID header is required.")
    if role is None or role == "":
        raise unauthenticated("X-User-Role header is required.")
    if role not in ROLES:
        raise unauthenticated("X-User-Role is not a recognized role.")
    return role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that the acting role is in the
    allowed set for the operation (priority 1 auth, then priority 2 authz)."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = authenticate()
            if role not in allowed:
                raise unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return deco
