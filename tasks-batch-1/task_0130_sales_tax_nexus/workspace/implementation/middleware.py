"""Authentication and RBAC (PRD §2.1, scaffold §1.4 priorities 1-2 and §1.7).

Two mandatory headers on every request:
  X-User-ID   — acting user id (for Seller this equals the Seller.id)
  X-User-Role — one of the five known roles

Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Known role not permitted for the operation -> ERR_UNAUTHORIZED (403).
"""
from functools import wraps

from flask import request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

KNOWN_ROLES = {"PlatformAdmin", "Seller", "TaxPreparer", "TaxApprover", "Auditor"}


def get_identity():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED if malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, "missing or invalid authentication headers")
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate then enforce that the role is in allowed_roles."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()  # raises 401 if bad
            if role not in allowed:
                raise APIError(ERR_UNAUTHORIZED, "role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return deco
