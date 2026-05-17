"""Auth middleware — PRD §2.1.

Every request carries X-User-ID and X-User-Role. Roles:
  BCBA, RBT, ClinicAdmin, PayerAdmin.

For BCBA/RBT, X-User-ID equals the acting Therapist.id and is used in
ownership checks against session.therapist_id, evaluation.evaluator_therapist_id,
etc. For ClinicAdmin/PayerAdmin, X-User-ID is opaque.
"""
from functools import wraps

from flask import g, request

from .errors import APIError


VALID_ROLES = {"BCBA", "RBT", "ClinicAdmin", "PayerAdmin"}


def _extract_headers():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if user_id is None or user_role is None or not user_id or not user_role:
        raise APIError("ERR_AUTH_REQUIRED", "X-User-ID and X-User-Role headers are required")
    if user_role not in VALID_ROLES:
        raise APIError("ERR_AUTH_REQUIRED", f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role


def require_auth(*allowed_roles):
    """Decorator that enforces authentication and (optional) RBAC.

    1. Both auth headers present + role recognised → otherwise ERR_AUTH_REQUIRED.
    2. If allowed_roles non-empty, role must be in the set → otherwise ERR_FORBIDDEN.
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
