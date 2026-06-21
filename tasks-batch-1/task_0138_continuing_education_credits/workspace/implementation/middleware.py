"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.10).

Every request must carry X-User-ID and X-User-Role. The four valid roles are
exactly: BoardAdmin, Provider, Licensee, Auditor.

Validation ordering (PRD §2.10): authentication (401) is checked before role
authorization (403). The require_roles decorator runs the auth check first, then
the role check, so a request from a permitted-but-unauthenticated caller fails
401 and an authenticated-but-wrong-role caller fails 403.
"""

import functools

from flask import g, request

import errors

VALID_ROLES = {"BoardAdmin", "Provider", "Licensee", "Auditor"}


def authenticate():
    """Extract and validate the auth headers. Raises ERR_UNAUTHENTICATED on failure.

    Populates flask.g.user_id and flask.g.user_role.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")

    if user_id is None or user_role is None:
        raise errors.unauthenticated("Missing X-User-ID or X-User-Role header.")
    user_id = user_id.strip()
    user_role = user_role.strip()
    if not user_id or not user_role:
        raise errors.unauthenticated("Empty X-User-ID or X-User-Role header.")
    if user_role not in VALID_ROLES:
        raise errors.unauthenticated(f"Unknown role '{user_role}'.")

    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that the acting role is allowed."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed_roles:
                raise errors.forbidden(
                    f"Role '{g.user_role}' is not permitted for this operation."
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
