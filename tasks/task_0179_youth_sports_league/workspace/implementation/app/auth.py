"""Authentication middleware utilities.

The PRD specifies that all endpoints — except /_clock/advance and a future
health probe — require X-User-ID and X-User-Role headers. Roles are:
LeagueAdmin, Coach, Referee, Guardian. For entity-backed roles (Coach,
Referee, Guardian) the X-User-ID must resolve to an existing entity of that
type, else ERR_FORBIDDEN.
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from flask import g, request

from .errors import raise_error
from .store import get_store


VALID_ROLES = {"LeagueAdmin", "Coach", "Referee", "Guardian"}


def _resolve_entity_for_role(role: str, user_id: str) -> Optional[dict]:
    store = get_store()
    if role == "Coach":
        return store.coaches.get(user_id)
    if role == "Referee":
        return store.referees.get(user_id)
    if role == "Guardian":
        return store.guardians.get(user_id)
    return None  # LeagueAdmin is opaque


def authenticate() -> None:
    """Populate flask.g with auth info or raise the appropriate APIError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error("ERR_AUTH_REQUIRED")
    if role not in VALID_ROLES:
        raise_error("ERR_FORBIDDEN")
    if role in ("Coach", "Referee", "Guardian"):
        entity = _resolve_entity_for_role(role, user_id)
        if entity is None:
            raise_error("ERR_FORBIDDEN")
        g.auth_entity = entity
    else:
        g.auth_entity = None
    g.user_id = user_id
    g.role = role


def require_roles(roles: Iterable[str]):
    """Decorator that enforces role membership AFTER authenticate() has run."""
    role_set = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if getattr(g, "role", None) not in role_set:
                raise_error("ERR_FORBIDDEN")
            return fn(*args, **kwargs)

        return wrapped

    return decorator
