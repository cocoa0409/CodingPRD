"""Authentication and RBAC middleware.

Implements the priority-ordered auth gate per §2.6 of the PRD:
  1. ERR_AUTH_HEADER_MISSING — either header absent
  2. ERR_AUTH_HEADER_INVALID — role string not in the four declared roles
  3. ERR_FORBIDDEN — role not permitted for this endpoint
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import APIError


VALID_ROLES = {
    "ProviderClinician",
    "ReviewingClinician",
    "SchoolRegistrar",
    "PublicHealthOfficer",
}


def _extract_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise APIError("ERR_AUTH_HEADER_MISSING", "X-User-ID and X-User-Role headers are required.")
    if role not in VALID_ROLES:
        raise APIError("ERR_AUTH_HEADER_INVALID", f"Unknown role: {role}")
    return user_id, role


def require_roles(allowed: Iterable[str]):
    """Decorator: extract auth headers, then verify the caller's role is allowed."""
    allowed_set = frozenset(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_headers()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed_set:
                raise APIError("ERR_FORBIDDEN", f"Role {role} not permitted for this endpoint.")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_auth():
    """Decorator for endpoints that need auth but accept any of the four roles."""
    return require_roles(VALID_ROLES)
