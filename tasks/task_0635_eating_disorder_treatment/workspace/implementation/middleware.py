"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Missing/malformed ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401). Present and well-formed but
role not permitted -> ERR_UNAUTHORIZED (403).

The five roles, spelled exactly: Admin, Intake, Clinician, Dietitian,
UtilizationReviewer. Identities are opaque operator strings; there are no
ownership checks keyed to X-User-ID (PRD §2.1).
"""
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

VALID_ROLES = {"Admin", "Intake", "Clinician", "Dietitian", "UtilizationReviewer"}


def require_auth_and_roles(allowed_roles):
    """Decorator: validates user-context headers (priority 1) then role (priority 2).

    These two checks run before any path/body processing, matching the fixed
    validation ordering of PRD §2.6.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")

            # Priority 1: header presence + well-formedness.
            if not user_id or not isinstance(user_id, str) or not user_id.strip():
                raise ApiError(
                    errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    401,
                    "Missing or invalid user context header.",
                )
            if not user_role or user_role not in VALID_ROLES:
                raise ApiError(
                    errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    401,
                    "Missing or invalid user context header.",
                )

            g.user_id = user_id
            g.user_role = user_role

            # Priority 2: role permitted for this operation.
            if user_role not in allowed_roles:
                raise ApiError(
                    errors.ERR_UNAUTHORIZED,
                    403,
                    "Role not permitted for this operation.",
                )

            return fn(*args, **kwargs)

        return wrapper

    return decorator
