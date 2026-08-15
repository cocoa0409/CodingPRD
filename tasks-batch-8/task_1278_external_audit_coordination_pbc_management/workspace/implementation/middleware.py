"""Auth header extraction and role checking per PRD §2.1 and scaffold §1.4."""
from flask import request
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

VALID_ROLES = ("Controller", "Preparer", "ExternalAuditor")


class UserContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_user_context():
    """Extract and validate X-User-ID / X-User-Role headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present",
            400,
        )
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or malformed",
            400,
        )
    return UserContext(user_id, role)


def require_roles(ctx, allowed_roles):
    """Check role admission for endpoint (priority 2)."""
    if ctx.role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
            403,
        )


def get_json_body():
    """Return parsed JSON body or empty dict; malformed JSON -> 400 auth error is
    NOT correct here — use ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER only for
    header issues. Malformed bodies surface as a generic 400."""
    if request.data:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            from errors import ApiError
            raise ApiError(
                ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                "Malformed request body",
                400,
            )
        if data is None:
            return {}
        if not isinstance(data, dict):
            return {}
        return data
    return {}


def parse_pagination():
    """Parse limit/offset query params with defaults per scaffold §1.0:
    limit default 10, min 1, max 100; offset default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset
