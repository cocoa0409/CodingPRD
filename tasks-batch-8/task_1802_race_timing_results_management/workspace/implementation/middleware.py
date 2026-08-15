"""Auth header extraction and role checking (PRD section 2.1)."""
from functools import wraps

from flask import request

import db
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ALL_ROLES = (
    "RaceDirector",
    "TimingOperator",
    "RegistrationClerk",
    "RaceOfficial",
    "CertificationOfficer",
    "Spectator",
)
STAFF_ROLES = ALL_ROLES[:5]


def endpoint(*roles):
    """Guard an endpoint: global lock + authentication + role authorization."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with db.lock:
                uid = request.headers.get("X-User-ID", "")
                role = request.headers.get("X-User-Role", "")
                if not uid or not uid.strip() or not role or not role.strip():
                    raise ApiError(
                        ERR_UNAUTHENTICATED,
                        401,
                        "X-User-ID and X-User-Role headers must be present and non-empty",
                    )
                if role not in roles:
                    raise ApiError(
                        ERR_UNAUTHORIZED_ROLE,
                        403,
                        "Role is not permitted for this endpoint",
                    )
                request.user_id = uid
                request.user_role = role
                return fn(*args, **kwargs)

        return wrapper

    return deco
