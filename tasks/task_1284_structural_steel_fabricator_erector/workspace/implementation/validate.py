"""Auth (ladder rungs 1-2), request-shape validation (rung 4), pagination,
and date/datetime parsing helpers."""

from datetime import date, datetime, timezone

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
)

ROLES = {
    "FABRICATOR_ADMIN",
    "DETAILER",
    "EOR",
    "FOREMAN",
    "WELDER",
    "QC_INSPECTOR",
    "GC_PM",
}

ALL_ROLES = ROLES


def authenticate():
    """Rung 1: X-User-Role present and recognized; X-User-ID present."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-ID and a recognized X-User-Role header are required.",
        )
    return uid, role


def require_role(role, allowed):
    """Rung 2: endpoint RBAC."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not permitted on this endpoint." % role)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a string." % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be an integer." % field)
    return v


def req_pos_int(body, field):
    v = req_int(body, field)
    if v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a positive integer." % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Field %s must be one of: %s." % (field, ", ".join(allowed)),
        )
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a boolean." % field)
    return v


def parse_iso_date(value, field):
    """Strict YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be an ISO date string." % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "Field %s must be an ISO date (YYYY-MM-DD)." % field
        )


def req_date(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    return parse_iso_date(v, field)


def parse_iso_datetime(value, field):
    """ISO 8601 datetime; naive values are read as UTC."""
    if not isinstance(value, str):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "Field %s must be an ISO8601 datetime string." % field
        )
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "Field %s must be an ISO8601 datetime." % field
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    return parse_iso_datetime(v, field)


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be at least 1.")
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be at least 0.")
    return limit, offset
