"""Auth header extraction and RBAC (PRD §2.1, §1.7).

Every request must carry two mandatory headers:
  X-User-ID   — identifies the acting user (opaque identity)
  X-User-Role — declares the operational capacity

Missing/malformed -> ERR_UNAUTHENTICATED (401).
Well-formed but role not permitted -> ERR_UNAUTHORIZED (403).
"""
from functools import wraps

from flask import request

import errors

VALID_ROLES = {
    "CareCoordinator",
    "Clinician",
    "Physician",
    "BillingSpecialist",
    "PayerAgent",
}


def get_identity():
    """Return (user_id, role) after validating presence/well-formedness.

    Raises ApiError(ERR_UNAUTHENTICATED) if either header is missing, empty,
    or carries an unrecognized role value.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.unauthenticated()
    if not isinstance(role, str) or role.strip() == "":
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that the role is in `allowed`.

    Stores (user_id, role) on flask.g for the handler to use.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from flask import g
            user_id, role = get_identity()
            if role not in allowed:
                raise errors.unauthorized()
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
