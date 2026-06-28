"""Auth header extraction and RBAC (PRD §2.1, §2.6, SCAFFOLD §1.4/§1.7).

Auth headers (authoritative per PRD §2.1):
  X-User-ID   — acting user id (for Customer this is the Customer.id)
  X-User-Role — one of StudioManager, Customer, FrontDesk, PlatformAdmin
"""
from functools import wraps

from flask import g, request

import errors
from errors import err

KNOWN_ROLES = {"StudioManager", "Customer", "FrontDesk", "PlatformAdmin"}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role known."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED,
                  "Missing or unknown X-User-ID / X-User-Role headers")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed):
    """Priority 2: acting role must be one of `allowed` (PlatformAdmin is a
    superset override and is always permitted)."""
    role = g.user_role
    if role == "PlatformAdmin":
        return
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN,
                  "Role %s not permitted for this operation" % role)


def is_customer():
    return g.user_role == "Customer"


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        authenticate()
        return fn(*args, **kwargs)
    return wrapper
