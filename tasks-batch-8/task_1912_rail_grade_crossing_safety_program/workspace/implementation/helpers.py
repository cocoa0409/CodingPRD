"""Request-body validation, parsing, pagination, and lookup helpers."""
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def body_or_empty():
    """Return the JSON body as a dict; empty/absent body becomes {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def reject_unknown(body, allowed):
    extra = sorted(set(body.keys()) - set(allowed))
    if extra:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"Unknown field(s): {', '.join(extra)}"
        )


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a string")
    return v


def req_int(body, name):
    v = body.get(name)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be an integer")
    return v


def opt_int(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an integer")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be a boolean")
    return v


def req_enum(body, name, values):
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field '{name}' must be one of: {', '.join(values)}",
        )
    return v


def req_int_range(body, name, lo, hi):
    v = req_int(body, name)
    if v < lo or (hi is not None and v > hi):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"Field '{name}' must be between {lo} and {hi}"
        )
    return v


def opt_int_range(body, name, lo, hi, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an integer")
    if v < lo or (hi is not None and v > hi):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"Field '{name}' must be between {lo} and {hi}"
        )
    return v


def parse_instant(v):
    """Parse an ISO 8601 instant (Z or offset). Returns aware UTC datetime or None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    try:
        if s.endswith(("Z", "z")):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_instant(body, name):
    raw = req_str(body, name)
    dt = parse_instant(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an ISO 8601 UTC timestamp")
    return raw, dt


def parse_date(v):
    """Parse a YYYY-MM-DD calendar date. Returns date or None."""
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def req_date(body, name):
    raw = req_str(body, name)
    d = parse_date(raw)
    if d is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an ISO calendar date (YYYY-MM-DD)")
    return raw, d


def get_or_404(collection, record_id, error_id, message):
    rec = collection.get(record_id)
    if rec is None:
        raise ApiError(error_id, 404, message)
    return rec


def paginate(items):
    """Offset pagination per PRD §2.3 (defaults: limit 10, offset 0; clamped)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def query_filter(name):
    return request.args.get(name)


def query_bool(name):
    """Boolean query filter value: 'true'/'false' (case-insensitive); else None."""
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return None
