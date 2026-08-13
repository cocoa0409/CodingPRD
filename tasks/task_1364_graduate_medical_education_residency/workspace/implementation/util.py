"""Parsing, validation, rounding, and pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

D2 = Decimal("0.01")
D1 = Decimal("0.1")
D0 = Decimal("1")


def round2(value):
    """Round a Decimal to 2 decimal places, half-up."""
    return Decimal(value).quantize(D2, rounding=ROUND_HALF_UP)


def round1(value):
    return Decimal(value).quantize(D1, rounding=ROUND_HALF_UP)


def round0_int(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(Decimal(value).quantize(D0, rounding=ROUND_HALF_UP))


def dec(value):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(value))


def parse_dt(value):
    """Parse a date-only ('YYYY-MM-DD') or full ISO 8601 timestamp to aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        dt = datetime.strptime(text, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_date_only(value):
    return isinstance(value, str) and len(value.strip()) == 10


def fmt_date(dt):
    return dt.strftime("%Y-%m-%d")


def fmt_dt(dt):
    """Full ISO 8601 UTC timestamp, seconds precision, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def invalid_request(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise invalid_request("Request body must be valid JSON")
        if not isinstance(data, dict):
            raise invalid_request("Request body must be a JSON object")
        return data
    return {}


def req_present(data, field):
    if field not in data or data[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_str(v, field):
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def as_int(v, field):
    if not _is_int(v):
        raise invalid_request(f"Field {field} must be an integer")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise invalid_request(f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        raise invalid_request(f"Field {field} must be one of {sorted(choices)}")
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise invalid_request(f"Field {field} must be an array")
    return v


def as_dt(v, field):
    """Validate a datetime-typed input string; returns the raw string for echo."""
    as_str(v, field)
    try:
        parse_dt(v)
    except Exception:
        raise invalid_request(f"Field {field} must be an ISO 8601 timestamp")
    return v


def as_version(v, field):
    """OCC expected_<parent>_version: integer (a numeric string is coerced)."""
    if _is_int(v):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    raise invalid_request(f"Field {field} must be an integer")


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset
