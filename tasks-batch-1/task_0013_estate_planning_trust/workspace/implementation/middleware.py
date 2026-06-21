"""Auth header extraction & RBAC. PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED


KNOWN_ROLES = {
    "EstatePlanner",
    "Executor",
    "Judge",
    "Beneficiary",
    "Registrar",
    "Creditor",
    "PlatformAdmin",
}


def extract_auth() -> tuple[Optional[str], Optional[str]]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allow_anonymous_planner_create: bool = False) -> None:
    """Raises ERR_UNAUTHENTICATED unless both headers present and role is known.

    `allow_anonymous_planner_create` is a no-op flag retained for clarity at the
    call site -- PRD §2.1 still requires X-User-Role=EstatePlanner with both
    headers present even for the 'anonymous-create' endpoints; only the
    *identity* is treated as opaque. We always require the two headers.
    """
    user_id, role = extract_auth()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, "Missing or invalid auth headers.", 401)
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles: str):
    """Decorator: caller must be one of the listed roles.

    Auth (presence of headers + known role) is checked first. If auth fails,
    ERR_UNAUTHENTICATED. If role is known but not in `allowed_roles`,
    ERR_UNAUTHORIZED.
    """

    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_auth()
            if g.user_role not in allowed:
                raise APIError(ERR_UNAUTHORIZED, "Role not permitted for this operation.", 403)
            return fn(*args, **kwargs)

        return wrapper

    return deco
