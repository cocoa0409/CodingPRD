"""Auth header extraction and role authorization (PRD section 2.1, validations 1-2).

Headers (exact names from PRD 2.1):
  X-User-ID   — acting user identifier
  X-User-Role — one of: Customer, ServiceAdvisor, Technician, ShopManager

Missing either header or unknown role -> ERR_UNAUTHENTICATED (401).
Valid headers but role not permitted for the endpoint -> ERR_FORBIDDEN (403).
Ownership for entity-backed roles is enforced per-endpoint via require_owner.
"""
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

VALID_ROLES = {"Customer", "ServiceAdvisor", "Technician", "ShopManager"}


def authenticate():
    """Validate auth headers; populate g.user_id and g.role. Raise on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "Missing or invalid authentication headers.")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that g.role is in the allowed set.

    Authentication (401) is always checked before authorization (403), per the
    validation priority ordering in PRD 2.8.
    """
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed_set:
                raise ApiError(errors.ERR_FORBIDDEN, 403,
                               "Role not permitted for this operation.")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
