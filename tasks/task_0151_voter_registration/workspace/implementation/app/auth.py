"""Authentication and RBAC (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The six legal roles
are: ElectionBoard, RegistrarClerk, ReviewerClerk, PrecinctOfficer,
Voter, TestDriver.

For Voter role, X-User-ID is the Voter.id; ownership checks compare
voter_id foreign keys to X-User-ID.
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Tuple

from flask import g, request

from .errors import err_forbidden, err_unauthenticated

VALID_ROLES = {
    "ElectionBoard",
    "RegistrarClerk",
    "ReviewerClerk",
    "PrecinctOfficer",
    "Voter",
    "TestDriver",
}


def authenticate() -> Tuple[str, str]:
    """Read X-User-ID + X-User-Role and validate them."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        raise err_unauthenticated("Unknown X-User-Role value")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed: Iterable[str]):
    """Decorator: authenticate then check role membership."""
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _uid, role = authenticate()
            if role not in allowed_set:
                raise err_forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user() -> Tuple[str, str]:
    return g.user_id, g.user_role
