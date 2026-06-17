"""Auth header extraction and RBAC checks (PRD §2.1, §2.10)."""
from functools import wraps

from flask import g, request

from errors import err

VALID_ROLES = {"RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice"}


def extract_user_context():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400) when either header is
    missing or malformed (empty, or role not one of the four recognized values).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID header is missing or malformed.",
        )
    if not role or role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role header is missing or malformed.",
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth headers (priority 1) then role permission (priority 2).

    Stashes the authenticated identity on flask.g for downstream handlers.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed_roles:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    "Role %s is not permitted for this operation." % role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
