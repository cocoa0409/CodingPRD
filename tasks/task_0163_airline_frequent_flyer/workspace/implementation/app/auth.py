"""Auth + RBAC middleware (PRD §2.1 / SCAFFOLD §1.7)."""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from . import errors as E


VALID_ROLES = {"Member", "BookingAgent", "ProgramAdmin"}


def parse_auth_headers():
    """Read and validate X-User-ID and X-User-Role.

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER for any failure.
    Stores parsed identity on flask.g.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise E.ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
            "Missing or invalid X-User-ID header.",
        )
    if not user_role or user_role not in VALID_ROLES:
        raise E.ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
            "Missing or invalid X-User-Role header.",
        )
    g.user_id = user_id.strip()
    g.user_role = user_role
    return g.user_id, g.user_role


def require_roles(*allowed: str):
    """Decorator: enforces auth header presence and role membership.

    Use roles=("*",) (or pass nothing) to mean any of the three valid roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = parse_auth_headers()
            if allowed and "*" not in allowed and user_role not in allowed:
                raise E.ApiError(
                    E.ERR_FORBIDDEN, 403,
                    f"Role {user_role} is not allowed on this endpoint.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_identity():
    return getattr(g, "user_id", None), getattr(g, "user_role", None)
