"""Authentication (X-User-ID / X-User-Role) and role-based authorization."""
from functools import wraps

from flask import request

import db
from errors import api_err

ROLES = (
    "CommitteeAdmin",
    "AgencyReviewer",
    "SafetyInspector",
    "Entrant",
    "Judge",
    "Marshal",
)

ALL_ROLES = None  # sentinel: any declared role


def guarded(roles):
    """Decorator: priority 1 (authentication) then priority 2 (role permission).

    Injects (user_id, role) as the first two handler arguments and serializes
    requests through a process-wide lock for cascade atomicity.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with db.LOCK:
                uid = request.headers.get("X-User-ID")
                role = request.headers.get("X-User-Role")
                if not uid or not role or role not in ROLES:
                    raise api_err(
                        "ERR_UNAUTHENTICATED",
                        "X-User-ID and X-User-Role headers are required and the role must be declared",
                    )
                if roles is not None and role not in roles:
                    raise api_err("ERR_FORBIDDEN", "Role is not permitted on this endpoint")
                return fn(uid, role, *args, **kwargs)

        return wrapper

    return deco


def require_owner(uid, owner_id):
    if uid != owner_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own this resource")
