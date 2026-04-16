"""Auth middleware: validates X-User-ID / X-User-Role headers and role entitlement."""

from functools import wraps
from flask import request, g

from errors import (
    APIError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    HTTP_STATUS,
)

VALID_ROLES = {
    "ShelterAdmin",
    "Veterinarian",
    "AdoptionReviewer",
    "AdoptionApprover",
    "HomeVisitInspector",
    "BoardingCoordinator",
    "FinanceOfficer",
    "Adopter",
}


def auth_required(allowed_roles=None):
    """allowed_roles is a set/list of role names. If None, 'Any' (authenticated) is allowed.

    'Any' means: any valid authenticated role may invoke.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip() or not role or not role.strip():
                raise APIError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
                    "Missing X-User-ID or X-User-Role",
                )
            if role not in VALID_ROLES:
                raise APIError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
                    f"Invalid role: {role}",
                )
            g.user_id = user_id
            g.user_role = role

            if allowed_roles is not None:
                if "Any" in allowed_roles:
                    pass  # any authenticated valid role
                elif role not in allowed_roles:
                    raise APIError(
                        ERR_INSUFFICIENT_PERMISSIONS,
                        HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                        f"Role {role} not permitted",
                    )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
