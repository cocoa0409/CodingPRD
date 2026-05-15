"""Authentication & RBAC middleware. PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {
    "ServicerAdmin",
    "ServicerCertifier",
    "ServicerApprover",
    "CollectionsOfficer",
    "Borrower",
    "SystemTest",
}


def _extract_auth(require_headers: bool = True) -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        if not require_headers:
            return "", ""
        raise ApiError("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_FORBIDDEN", f"Unknown role: {role!r}")
    return user_id, role


def require_auth(*allowed_roles: str) -> Callable:
    """Decorator: validates headers and ensures the role is in the allowed set."""
    allowed = set(allowed_roles) if allowed_roles else set(VALID_ROLES)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapped(*args, **kwargs):
            user_id, role = _extract_auth()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN",
                    f"Role {role!r} not permitted for {request.path}.",
                )
            return func(*args, **kwargs)

        return wrapped

    return decorator


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", ""), getattr(g, "user_role", "")


def verify_borrower_ownership(borrower_id: str) -> None:
    """If the actor is a Borrower, ensure their X-User-ID matches borrower_id.
    Otherwise no-op."""
    user_id, role = current_actor()
    if role == "Borrower" and user_id != borrower_id:
        # Per PRD §2.1: a borrower may not read or mutate another borrower's resources.
        # This appears as a 403 since RBAC restricts access.
        raise ApiError("ERR_FORBIDDEN", "Borrower may only access own resources.")
