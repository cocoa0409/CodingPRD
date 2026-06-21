"""Auth header extraction & RBAC. PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import g, request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


# The system recognizes exactly four roles. PRD §2.1.
KNOWN_ROLES = {"Administrator", "BoardApprover", "Stakeholder", "Auditor"}


def extract_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth() -> None:
    """Raise ERR_UNAUTHENTICATED unless both headers present and role is known."""
    user_id, role = extract_auth()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, "Missing or invalid auth headers.", 401)
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles: str):
    """Decorator: caller must authenticate, then be one of the listed roles.

    Auth (presence of headers + known role) is checked first -> ERR_UNAUTHENTICATED.
    Known but disallowed role -> ERR_FORBIDDEN.
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_auth()
            if g.user_role not in allowed:
                raise APIError(ERR_FORBIDDEN, "Role not permitted for this operation.", 403)
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def is_stakeholder() -> bool:
    return current_role() == "Stakeholder"
