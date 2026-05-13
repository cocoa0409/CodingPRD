"""Auth and request-context middleware."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import err

VALID_ROLES = {"ProjectManager", "Translator"}


def extract_identity():
    user_id = request.headers.get("X-User-ID", "")
    user_role = request.headers.get("X-User-Role", "")
    if not user_id or not user_role:
        raise err("ERR_UNAUTHENTICATED", "Missing or empty X-User-ID / X-User-Role headers.")
    if user_role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role.")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*roles: str):
    """Decorator: extract identity, then require the role be in the allowed list."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            extract_identity()
            if g.user_role not in roles:
                raise err("ERR_FORBIDDEN", f"Role {g.user_role} cannot access this endpoint.")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        extract_identity()
        return fn(*args, **kwargs)
    return wrapper
