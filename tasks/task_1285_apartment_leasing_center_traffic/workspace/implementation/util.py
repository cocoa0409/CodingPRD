"""Parsing, validation, and pagination helpers."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def opt(data, field, default=None):
    """Optional field; an explicit JSON null falls back to the default."""
    v = data.get(field, default)
    return default if v is None else v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_nonneg_int(v, field):
    v = as_int(v, field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must not be negative")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")
    return v


def as_enum(v, field, members):
    if not isinstance(v, str) or v not in members:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be one of: {', '.join(members)}",
        )
    return v


def as_dt(v, field):
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime"
        )


def pagination():
    """limit/offset query params: default 10/0, limit in [1, 100] (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must not be negative")
    return limit, offset


def apply_filters(items, mapping):
    """Exact-match query filters; unknown filter values simply match nothing."""
    out = list(items)
    for param, field in mapping:
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if r.get(field) == v]
    return out
