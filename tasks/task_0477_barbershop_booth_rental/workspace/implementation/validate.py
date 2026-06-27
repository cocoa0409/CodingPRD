"""Body parsing, field validation, pagination, datetime parsing helpers."""
from datetime import datetime, timezone

from flask import request

import errors


def body():
    """Return the JSON body as a dict, or {} when absent. Bad JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Body must be a JSON object.")
    return data


def require(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {n}")


def as_str(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, str) or v == "":
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string.")
    return v


def as_int(data, name, required=True, default=None, min_v=None, max_v=None):
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer.")
    if min_v is not None and v < min_v:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} below minimum {min_v}.")
    if max_v is not None and v > max_v:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} above maximum {max_v}.")
    return v


def as_number(data, name, required=True, default=None, min_v=None, max_v=None):
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number.")
    if min_v is not None and v < min_v:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} below minimum {min_v}.")
    if max_v is not None and v > max_v:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} above maximum {max_v}.")
    return v


def as_bool(data, name, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean.")
    return v


def as_enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if v not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}.")
    return v


def as_str_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default) if default is not None else []
    v = data[name]
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an array of strings.")
    return list(v)


def parse_dt(data, name, required=True, default=None):
    """Parse an ISO 8601 datetime field. Returns aware UTC datetime."""
    if name not in data or data[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime string.")
    return parse_iso_dt(v, name)


def parse_iso_dt(v, name="datetime"):
    text = v.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(v, name="date"):
    """Parse a YYYY-MM-DD calendar date string into a date object."""
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a date string.")
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO date (YYYY-MM-DD).")


def pagination():
    """Read limit/offset query params with defaults 10/0, min 1, max 100."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def paginate(items):
    """Sort by creation order, slice, and produce pagination meta."""
    limit, offset = pagination()
    ordered = sorted(items, key=lambda o: o.get("_seq", 0))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta
