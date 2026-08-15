"""Parsing, validation, rounding, and pagination helpers."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_ymd(value):
    """Parse a YYYY-MM-DD date string into a date."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            _bad("Request body must be valid JSON")
        if not isinstance(data, dict):
            _bad("Request body must be a JSON object")
        return data
    return {}


def req_field(data, field):
    if field not in data or data[field] is None:
        _bad(f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = req_field(data, field)
    if not isinstance(v, str):
        _bad(f"Field {field} must be a string")
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = req_field(data, field)
    if not _is_int(v):
        _bad(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _bad(f"Field {field} must be <= {maximum}")
    return v


def req_bool(data, field):
    v = req_field(data, field)
    if not isinstance(v, bool):
        _bad(f"Field {field} must be a boolean")
    return v


def req_enum(data, field, choices):
    v = req_field(data, field)
    if v not in choices:
        _bad(f"Field {field} must be one of {sorted(choices)}")
    return v


def req_iso_dt(data, field):
    v = req_str(data, field)
    try:
        return v, parse_dt(v)
    except Exception:
        _bad(f"Field {field} must be an ISO 8601 timestamp")


def req_date(data, field):
    v = req_str(data, field)
    try:
        return v, parse_ymd(v)
    except Exception:
        _bad(f"Field {field} must be a YYYY-MM-DD date")


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
    if limit < 1 or limit > 100:
        _bad("limit must be between 1 and 100")
    if offset < 0:
        _bad("offset must be >= 0")
    return limit, offset
