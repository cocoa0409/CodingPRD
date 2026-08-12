"""Auth header extraction, role checking, body/query helpers (PRD §2.1, §2.3, §2.9)."""
from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST

ROLES = {
    "DistrictAdmin",
    "SchoolAdministrator",
    "HearingOfficer",
    "ParentGuardian",
    "StudentServicesDirector",
}


class Ctx:
    def __init__(self, user_id, role, body):
        self.user_id = user_id
        self.role = role
        self.body = body


def endpoint(*roles):
    """Decorator implementing validation ladder rungs 1-2 (auth, role)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    ERR_UNAUTHENTICATED[0],
                    ERR_UNAUTHENTICATED[1],
                    "Missing or unrecognized X-User-Role / X-User-ID header",
                )
            if role not in roles:
                raise ApiError(
                    ERR_UNAUTHORIZED[0],
                    ERR_UNAUTHORIZED[1],
                    "Role not permitted for this endpoint",
                )
            body = request.get_json(silent=True)
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError(
                    ERR_INVALID_REQUEST[0],
                    ERR_INVALID_REQUEST[1],
                    "Request body must be a JSON object",
                )
            return fn(Ctx(user_id, role, body), *args, **kwargs)

        return wrapper

    return deco


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(
                ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "limit must be an integer"
            )
        if limit < 1 or limit > 100:
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "limit must be between 1 and 100",
            )
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(
                ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "offset must be an integer"
            )
        if offset < 0:
            raise ApiError(
                ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "offset must be >= 0"
            )
    return limit, offset
