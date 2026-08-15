"""Shared utilities: datetime parsing/serialization, input validation, pagination."""

from datetime import datetime, timezone

from flask import request

import errors


def parse_dt(value, field="date"):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime.

    Accepts 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SSZ', offsets, fractional seconds.
    Raises ApiError(ERR_INVALID_REQUEST) on failure.
    """
    if not isinstance(value, str):
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            f"Field '{field}' must be an ISO 8601 string",
            400,
        )
    s = value.strip()
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            f"Field '{field}' is not a valid ISO 8601 date/datetime: {value!r}",
            400,
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_wall_iso():
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


# ---- input validation helpers ----

def get_body():
    """Return the JSON request body as a dict; {} for empty bodies."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string", 400)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid required integer field: {field}", 400)
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer", 400)
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean", 400)
    return v


def req_number(body, field):
    """A number that may be int or float (but not bool)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing or invalid numeric field: {field}", 400)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            f"Field '{field}' must be one of {sorted(allowed)}",
            400,
        )
    return v


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    return parse_dt(v, field)


# ---- pagination ----

def parse_pagination():
    """limit defaults to 10 (min 1, max 100), offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    """items: list already sorted by created_at ascending (then id for stability)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
