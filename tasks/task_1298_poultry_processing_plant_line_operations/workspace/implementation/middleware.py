"""Auth header extraction and role checking per PRD section 2.1."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
)

ROLES = {
    "PlantManager",
    "ShiftSupervisor",
    "ReceivingClerk",
    "LineOperator",
    "QATechnician",
    "SanitationLead",
    "USDAInspector",
    "OrderPlanner",
}

ALL_ROLES = ROLES  # "All roles" on GET endpoints means any declared role


def current_user():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ApiError(400) if missing/invalid.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or role not a declared role",
            400,
        )
    return user_id, role


def require_roles(*allowed):
    """Validate auth context and that the caller's role is among `allowed`.

    Returns (user_id, role).
    """
    user_id, role = current_user()
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this operation",
            403,
        )
    return user_id, role


def get_json_body():
    """Return the parsed JSON body, or raise ERR_INVALID_REQUEST if malformed."""
    body = request.get_json(silent=True)
    if body is None:
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST, "Malformed JSON body", 400)
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def check_required(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {f}", 400)


def check_no_unknown(body, allowed_fields):
    for k in body:
        if k not in allowed_fields:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown field: {k}", 400)


def check_enum(value, allowed, field_name):
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Invalid value for {field_name}: {value}",
            400,
        )


def check_int(value, field_name, min_value=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be an integer", 400)
    if min_value is not None and value < min_value:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field_name} must be >= {min_value}",
            400,
        )


def check_number(value, field_name, min_value=None, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a number", 400)
    if min_value is not None:
        if exclusive_min and value <= min_value:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"{field_name} must be > {min_value}",
                400,
            )
        if not exclusive_min and value < min_value:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"{field_name} must be >= {min_value}",
                400,
            )


def check_string(value, field_name):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a string", 400)


def parse_iso8601(value, field_name):
    """Parse an ISO 8601 datetime string; returns an aware UTC datetime."""
    from datetime import timezone, datetime

    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be an ISO8601 string", 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """Parse limit/offset query params with defaults 10/0, min 1, max 100."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset
