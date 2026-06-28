"""Auth + RBAC (PRD 2.1, scaffold §1.4 priority 1-2 and §1.7).

Validation priority order (PRD 2.8):
  1. auth context present (401)
  2. role permitted (403)
...handled per-endpoint by calling require(role-set) at the top of each handler,
after auth context has been established by the before_request hook.
"""
from functools import wraps

from flask import g, request

import errors

VALID_ROLES = {"PracticeAdmin", "FrontDesk", "Provider", "PathLab", "BillingSpecialist"}


def extract_auth():
    """PRD 2.1: every request must carry X-User-ID and X-User-Role.

    If either is missing or malformed, ERR_MISSING_AUTH_CONTEXT (401).
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise errors.missing_auth()
    if not user_role or user_role not in VALID_ROLES:
        # A role string that is not one of the five recognized roles is malformed
        # auth context.
        raise errors.missing_auth()
    g.user_id = user_id
    g.user_role = user_role


def require(*allowed_roles):
    """Decorator: enforce that the caller's role is among allowed_roles."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.get("user_role") not in allowed:
                raise errors.forbidden_role()
            return fn(*args, **kwargs)
        return wrapper
    return deco
