"""Authentication / authorization middleware helpers.

Per PRD §2.1 and SCAFFOLD.yaml priority-1/2 validations:
  * Headers required on every request: X-User-ID, X-User-Role
  * Role must be one of: Consumer, BureauOperator, Furnisher, CFPBOperator, PlatformAdmin
  * For consumer-scoped resources, X-User-ID (when role=Consumer) must equal the
    resource's consumer_id, else ERR_FORBIDDEN_FOR_ROLE.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import request

from .errors import ApiError


VALID_ROLES = {"Consumer", "BureauOperator", "Furnisher", "CFPBOperator", "PlatformAdmin"}


def _read_user_context() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required.",
            400,
        )
    if not isinstance(user_id, str) or not isinstance(user_role, str):
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be strings.",
            400,
        )
    if not user_id.strip() or not user_role.strip():
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must not be empty.",
            400,
        )
    if user_role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            f"Unknown role '{user_role}'.",
            400,
        )
    return user_id, user_role


def require_auth(allowed_roles: Iterable[str]) -> Callable:
    """Decorator: validates headers (priority 1) and role (priority 2).

    Ownership checks (consumer_id matching) are done per-route because the
    consumer_id source varies (path param vs body vs target resource).
    """
    allowed = frozenset(allowed_roles)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = _read_user_context()
            if user_role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN_FOR_ROLE",
                    f"Role '{user_role}' is not permitted for this endpoint.",
                    403,
                )
            # Stash on flask.g for downstream use.
            from flask import g

            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_principal() -> tuple[str, str]:
    """Read (user_id, user_role) inside a request context."""
    from flask import g

    return g.user_id, g.user_role


def enforce_consumer_ownership(consumer_id: str) -> None:
    """If the caller is a Consumer, X-User-ID must equal consumer_id."""
    user_id, user_role = current_principal()
    if user_role == "Consumer" and user_id != consumer_id:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Consumer may only act on their own resources.",
            403,
        )


def enforce_furnisher_ownership(furnisher_id: str) -> None:
    """If the caller is a Furnisher, X-User-ID must equal furnisher_id."""
    user_id, user_role = current_principal()
    if user_role == "Furnisher" and user_id != furnisher_id:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Furnisher may only act on their own resources.",
            403,
        )
