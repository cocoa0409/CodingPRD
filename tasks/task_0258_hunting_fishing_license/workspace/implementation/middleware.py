"""Auth header extraction and role checking (PRD §2.1).

Mandatory headers: X-User-ID, X-User-Role.
Roles (spelled precisely): Applicant, LicenseAgent, DrawOfficer, GameWarden.
"""
from functools import wraps

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"Applicant", "LicenseAgent", "DrawOfficer", "GameWarden"}


def get_identity():
    """Return (user_id, role), validating presence/well-formedness.

    Raises ERR_UNAUTHENTICATED if either header is missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err(ERR_UNAUTHENTICATED, "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unrecognized X-User-Role value")
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then authorize against the allowed role set.

    Authentication (ERR_UNAUTHENTICATED) is checked before authorization
    (ERR_UNAUTHORIZED) per PRD §2.6.
    """
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed_set:
                raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation")
            request.user_id = user_id
            request.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
