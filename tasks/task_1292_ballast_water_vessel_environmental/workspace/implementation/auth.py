"""Authentication and role-based authorization per PRD sections 2.1 and 2.10."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = (
    "PlatformAdmin",
    "ShoreComplianceOfficer",
    "VesselMaster",
    "FlagSurveyor",
    "PSCOfficer",
)

# PRD 2.1: the platform administrator owns only the clock endpoint and
# otherwise shares read access, so every GET endpoint accepts all five roles.
ALL_ROLES = ROLES


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not uid or not role or role not in ROLES:
                raise ApiError(ERR_UNAUTHENTICATED, 401,
                               "X-User-ID and X-User-Role headers are required "
                               "and the role must be recognized")
            if allowed and role not in allowed:
                raise ApiError(ERR_UNAUTHORIZED, 403,
                               "role %s is not permitted for this endpoint" % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
