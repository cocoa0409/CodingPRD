"""Request parsing, datetime handling, and pagination helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err, ERR_INVALID_REQUEST


def get_json_body():
    """Return the parsed JSON body as a dict (or {} when empty). Raises
    ERR_INVALID_REQUEST when the body is present but not a JSON object."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.
    Raises ERR_INVALID_REQUEST on a bad value."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_midnight(dt, field):
    """ISO 8601 UTC midnight constraint."""
    if not (dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0):
        raise err(ERR_INVALID_REQUEST, "Field %s must be ISO 8601 UTC midnight" % field)


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return value


def require_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return value


def require_str(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return value


def require_nonempty_str(value, field):
    require_str(value, field)
    if not value.strip():
        raise err(ERR_INVALID_REQUEST, "Field %s must be non-empty" % field)
    return value


def require_enum(value, field, allowed):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def parse_pagination():
    """Parse limit/offset query params with bounds (PRD §2.3).
    limit default 10, min 1, max 100; offset default 0, min 0.
    Out-of-bounds => ERR_INVALID_REQUEST (400)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit out of bounds (1..100)")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset out of bounds (>= 0)")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
