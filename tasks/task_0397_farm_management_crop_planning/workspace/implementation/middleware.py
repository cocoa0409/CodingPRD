"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.10).

Headers (verbatim from PRD §2.1):
  X-User-ID   : acting user id (entity-backed only for Applicator)
  X-User-Role : one of FarmManager | Agronomist | Applicator | SalesAgent

Validation order (PRD §2.10): auth (401) -> authorization (403) -> ... .
"""
from functools import wraps

from flask import request

from errors import err

RECOGNIZED_ROLES = {"FarmManager", "Agronomist", "Applicator", "SalesAgent"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def authenticate():
    """PRD §2.1: X-User-Role must be present and recognized, else ERR_UNAUTHENTICATED."""
    role = get_role()
    if not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header.")
    return role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce RBAC (PRD §2.10).

    GET (read) endpoints pass all four roles since all roles have read access.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = authenticate()
            if role not in allowed_roles:
                raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
