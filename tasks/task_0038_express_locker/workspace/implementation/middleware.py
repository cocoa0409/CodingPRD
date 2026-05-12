"""Auth header extraction and role checking — per PRD §2.1.

Headers: X-User-ID, X-User-Role.
Valid roles: OperationsAdmin, Courier, Recipient, Any.
"""

from functools import wraps

from flask import g, request

from errors import APIError, bad_header, forbidden


VALID_ROLES = {"OperationsAdmin", "Courier", "Recipient", "Any"}


def extract_auth():
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not user_id or not role:
        raise bad_header()
    if role not in VALID_ROLES:
        raise bad_header(f"Unknown role: {role}")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce that current role is in the allowed set."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "role", None) not in allowed:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
