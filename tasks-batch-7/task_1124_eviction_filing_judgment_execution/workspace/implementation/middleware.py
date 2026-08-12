from functools import wraps

from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "Landlord",
    "CourtClerk",
    "ProcessServer",
    "SheriffDeputy",
    "Mediator",
}


def auth(allowed):
    """Rung 1 (authentication) then rung 2 (endpoint role authorization)."""
    allowed = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    401,
                    "Missing/invalid X-User-Role or X-User-ID",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN", 403, "Role not permitted for endpoint"
                )
            return fn(*args, _uid=uid, _role=role, **kwargs)

        return wrapper

    return deco


def require_owner(uid, landlord_id):
    if uid != landlord_id:
        raise ApiError(
            "ERR_NOT_OWNER",
            403,
            "X-User-ID does not own the aggregate chain being mutated",
        )
