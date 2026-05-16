"""Auth middleware: header validation + role/permission checks.

Per PRD §2.1, every request must carry X-User-ID and X-User-Role. The role
enumeration is case-sensitive and limited to:
    Candidate, Proctor, AccommodationsOfficer, Registrar, CreditsOfficer.

When the role is Candidate, X-User-ID must equal the Candidate.id row for
ownership-checked endpoints. For other roles, X-User-ID is an opaque operator
identifier.
"""

from functools import wraps

from flask import g, request

from config import ROLES
from errors import (
    err_insufficient_permissions,
    err_missing_or_invalid_user_context_header,
)


def parse_headers():
    """Validate auth headers and stash on flask.g. Raises APIError if malformed."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")

    if user_id is None or user_role is None:
        raise err_missing_or_invalid_user_context_header()
    if not isinstance(user_id, str) or not isinstance(user_role, str):
        raise err_missing_or_invalid_user_context_header()
    if not user_id.strip() or not user_role.strip():
        raise err_missing_or_invalid_user_context_header()
    if user_role not in ROLES:
        # Any role value outside the enum is treated as malformed.
        raise err_missing_or_invalid_user_context_header()

    g.user_id = user_id
    g.user_role = user_role


def require_roles(*allowed_roles):
    """Decorator: require the caller's role to be in allowed_roles.

    Header parsing is performed first; that error wins over role mismatch.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            parse_headers()
            if g.user_role not in allowed_roles:
                raise err_insufficient_permissions()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id() -> str:
    return g.user_id


def current_user_role() -> str:
    return g.user_role
