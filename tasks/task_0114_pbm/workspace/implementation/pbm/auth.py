"""Authentication / RBAC middleware.

Headers per PRD §2.1:
- `X-User-ID`  — opaque operator identifier
- `X-User-Role` — one of: PBMAdmin, Prescriber, ClinicalReviewer, ClaimsAdjudicator

Missing/empty headers -> ERR_UNAUTHENTICATED (401).
Role not authorised for endpoint -> ERR_FORBIDDEN (403).
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import request

from .errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
)


ROLES = {"PBMAdmin", "Prescriber", "ClinicalReviewer", "ClaimsAdjudicator"}


def get_caller():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise APIError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header", 401)
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: caller must present a valid role from the allowed set."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_caller()
            if role not in ROLES:
                # An unknown role is treated as forbidden, not unauth.
                raise APIError(ERR_FORBIDDEN, f"Role '{role}' is not recognised", 403)
            if role not in allowed_set:
                raise APIError(ERR_FORBIDDEN, f"Role '{role}' is not authorised for this endpoint", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
