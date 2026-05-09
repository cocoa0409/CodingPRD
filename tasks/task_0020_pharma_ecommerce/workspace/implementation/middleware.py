"""Auth header parsing and RBAC helpers (PRD §2.1)."""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import err

VALID_ROLES = {
    "PlatformAdmin",
    "VendorAdmin",
    "PrescriptionReviewer",
    "PharmacistReReviewer",
    "Pharmacist",
    "Customer",
    "RegulatoryGateway",
}


def _extract_user_context():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required.",
        )
    if not isinstance(user_id, str) or not isinstance(user_role, str):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if user_role.strip() == "" or user_id.strip() == "":
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if user_role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            f"Unknown role '{user_role}'.",
        )
    g.user_id = user_id
    g.user_role = user_role


def require_auth(skip: bool = False):
    """Decorator: validate the auth headers (priority 1) and store on flask.g."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not skip:
                _extract_user_context()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_roles(*roles: str):
    """Decorator: enforce that the caller's X-User-Role is in `roles` (priority 2)."""

    role_set = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_user_context()
            if g.user_role not in role_set:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    f"Role '{g.user_role}' is not permitted for this operation.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", "system"), getattr(g, "user_role", "system")
