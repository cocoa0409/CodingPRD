"""Authentication middleware: X-User-ID / X-User-Role headers (per PRD §2.1)."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable, Optional

from flask import g, request

from .errors import APIError

ROLE_CLAIMANT = "Claimant"
ROLE_ADJUDICATOR = "Adjudicator"
ROLE_APPEAL_OFFICER = "AppealOfficer"
ROLE_EMPLOYER_AGENT = "EmployerAgent"
ROLE_SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = {
    ROLE_CLAIMANT,
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_EMPLOYER_AGENT,
    ROLE_SYSTEM_ADMIN,
}


def _read_identity() -> None:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise APIError("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role", 401)
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise APIError("ERR_UNAUTHENTICATED", "Malformed identity headers", 401)
    if role not in ALL_ROLES:
        raise APIError("ERR_UNAUTHENTICATED", f"Unknown role: {role}", 401)
    g.user_id = user_id
    g.user_role = role


def require_auth(roles: Optional[Iterable[str]] = None) -> Callable:
    """Decorator: authenticate first, then enforce role list."""
    allowed = set(roles) if roles is not None else None

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _read_identity()
            if allowed is not None and g.user_role not in allowed:
                raise APIError(
                    "ERR_FORBIDDEN",
                    f"Role {g.user_role} not permitted for this endpoint",
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.user_role


def is_claimant() -> bool:
    return getattr(g, "user_role", None) == ROLE_CLAIMANT


def is_employer_agent() -> bool:
    return getattr(g, "user_role", None) == ROLE_EMPLOYER_AGENT
