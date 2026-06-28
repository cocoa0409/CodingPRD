"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.7)."""

from functools import wraps

from flask import request

import errors
from errors import ApiError

# PRD §2.1: exactly four roles, spelled precisely.
KNOWN_ROLES = {"ClinicAdmin", "SchedulingCoordinator", "Evaluator", "Therapist"}


def get_auth():
    """Return (user_id, role) after validating the auth headers.

    PRD §2.1: every request must be authenticated through X-User-ID and
    X-User-Role. If either is missing, or X-User-Role does not name a known
    role, reject with ERR_MISSING_OR_INVALID_AUTH (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_AUTH,
            401,
            "Missing or invalid authentication headers.",
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth, then enforce that role is permitted (PRD §2.1).

    The wrapped view receives keyword args user_id and role.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed_roles:
                raise ApiError(
                    errors.ERR_FORBIDDEN_ROLE,
                    403,
                    "Role not permitted for this operation.",
                )
            kwargs["user_id"] = user_id
            kwargs["role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# All four roles share read access (PRD §2.1).
ALL_ROLES = ("ClinicAdmin", "SchedulingCoordinator", "Evaluator", "Therapist")
