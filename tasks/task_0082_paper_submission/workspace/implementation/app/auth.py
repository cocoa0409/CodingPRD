"""Authentication and RBAC middleware.

Per PRD §2.1: every request must carry X-User-ID and X-User-Role headers.
Roles are case-sensitive and must be one of:
    PlatformAdmin, Author, EditorInChief, SectionEditor, AssociateEditor, Reviewer
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import api_error


VALID_ROLES = {
    "PlatformAdmin",
    "Author",
    "EditorInChief",
    "SectionEditor",
    "AssociateEditor",
    "Reviewer",
}


def parse_auth():
    """Extract X-User-ID/X-User-Role; raise ERR_AUTH_REQUIRED if invalid."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise api_error("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise api_error("ERR_AUTH_REQUIRED", f"Unrecognised role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_auth(roles: Iterable[str]):
    """Decorator: ensure auth headers are present and role is permitted."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = parse_auth()
            if role not in allowed:
                raise api_error("ERR_FORBIDDEN", f"Role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
