"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.4/§1.7).

Every request must carry X-User-ID and X-User-Role. The four recognized roles
are Admin, Agent, Underwriter, Inspector. Auth (priority 1) is checked before
authorization (priority 2).
"""
from functools import wraps

from flask import request, g

from errors import err

VALID_ROLES = {"Admin", "Agent", "Underwriter", "Inspector"}


def extract_user_context():
    """Validate the user-context headers. Raises on missing/invalid (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and valid.",
        )
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: validate user context, then enforce role allow-list (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            if role not in allowed:
                raise err(
                    "ERR_UNAUTHORIZED",
                    "The acting role is not permitted for this operation.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
