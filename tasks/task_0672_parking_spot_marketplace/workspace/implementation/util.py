"""Shared parsing / validation utilities."""
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_PAGINATION


def parse_iso8601(value):
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime (UTC).

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure (caller
    decides which error to raise).
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_body(data):
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require_field(data, field):
    if field not in data or data[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}.")
    return data[field]


def require_str(data, field):
    val = require_field(data, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string.")
    return val


def require_int(data, field):
    val = require_field(data, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    return val


def optional_int(data, field, default):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    return val


def require_enum(data, field, allowed):
    val = require_field(data, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return val


def require_datetime(data, field):
    raw = require_field(data, field)
    dt = parse_iso8601(raw)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 UTC instant.")
    return dt


def parse_pagination(args):
    """Parse limit/offset from query args. limit in [1,100] default 10; offset >= 0 default 0.

    Raises ERR_INVALID_PAGINATION on out-of-range or malformed values.
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_PAGINATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_PAGINATION, "limit must be within [1,100].")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_PAGINATION, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_INVALID_PAGINATION, "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice for already-sorted items."""
    return items[offset:offset + limit]
