"""Authentication and RBAC."""
from __future__ import annotations
from functools import wraps

from flask import g, request

from core.errors import raise_error

VALID_ROLES = {"Applicant", "Recommender", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers and stash them on flask.g."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error("ERR_AUTH_MISSING")
    if user_role not in VALID_ROLES:
        raise_error("ERR_AUTH_INVALID_ROLE")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles: str):
    """Decorator to enforce that g.user_role is one of `roles`."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                raise_error("ERR_FORBIDDEN")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.user_role
