"""Auth middleware — PRD §2.1.

Identity headers: X-User-ID and X-User-Role.
Six recognized roles: PlatformAdmin, Provider, InitialReviewer, MedicalDirector,
ExternalReviewer, PayerReviewer.

Per PRD §2.1, when X-User-Role is Provider, X-User-ID equals the acting
Provider entity's id and is used for ownership checks. Other roles use an
opaque operator id not tied to any entity.
"""
from functools import wraps

from flask import g, request

from .errors import APIError


VALID_ROLES = {
    "PlatformAdmin",
    "Provider",
    "InitialReviewer",
    "MedicalDirector",
    "ExternalReviewer",
    "PayerReviewer",
}


def _extract_headers():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    # Both headers must be present and well-formed (non-empty + a recognized role).
    if user_id is None or user_role is None or not user_id or not user_role:
        raise APIError("ERR_AUTH_MISSING", "X-User-ID and X-User-Role headers are required")
    if user_role not in VALID_ROLES:
        raise APIError("ERR_AUTH_MISSING", f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role


def require_auth(*allowed_roles):
    """Decorator:
      1) ensures both auth headers are present and the role is recognized (ERR_AUTH_MISSING).
      2) when allowed_roles is non-empty, role must be in the set (ERR_FORBIDDEN).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_headers()
            if allowed_roles and g.user_role not in allowed_roles:
                raise APIError(
                    "ERR_FORBIDDEN", f"Role {g.user_role} not permitted on this endpoint"
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
