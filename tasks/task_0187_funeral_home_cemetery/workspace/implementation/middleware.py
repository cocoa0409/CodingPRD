"""Auth header extraction + RBAC (PRD §2.1, §2.9; SCAFFOLD §1.4, §1.7).

Two mandatory headers per request:
  X-User-ID   — opaque operator identifier (never compared to entity ids)
  X-User-Role — one of: Admin, Arranger, TrustOfficer, CemeteryClerk, Registrar

Missing X-User-ID, missing X-User-Role, or an unrecognized role => ERR_UNAUTHENTICATED (401).
A recognized-but-unauthorized role for an operation => ERR_FORBIDDEN (403).

Validation priority (PRD §2.9): auth(1) -> authz(2) -> existence(3) -> ...
So the auth+role check happens before any resource lookup.
"""
from functools import wraps

from flask import request, g

import errors

KNOWN_ROLES = {"Admin", "Arranger", "TrustOfficer", "CemeteryClerk", "Registrar"}


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate then check role membership against allowed_roles."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _user_id, role = _authenticate()
            if role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
