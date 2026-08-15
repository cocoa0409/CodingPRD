"""Parsing, validation, rounding, and pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

_CENT = Decimal("1")
_SHARE_Q = Decimal("0.0001")


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


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    n = dt.astimezone(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def round_cents(value):
    """Round a Decimal to the nearest integer cent, half-up."""
    return int(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def round4(value):
    """Round a Decimal share quantity to four decimal places, half-up."""
    return value.quantize(_SHARE_Q, rounding=ROUND_HALF_UP)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


def as_pos_int(v, field):
    v = as_int(v, field)
    if v <= 0:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field {field} must be a positive integer"
        )
    return v


def as_nonneg_int(v, field):
    v = as_int(v, field)
    if v < 0:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field {field} must be a non-negative integer"
        )
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def as_decimal(v, field, error_id="ERR_VALIDATION", status=400):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(error_id, status, f"Field {field} must be a number")
    d = Decimal(str(v))
    if not d.is_finite():
        raise ApiError(error_id, status, f"Field {field} must be a finite number")
    return d


def as_enum(v, field, choices, error_id="ERR_VALIDATION", status=400):
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            error_id, status, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_iso_dt(v, field):
    as_str(v, field)
    try:
        parse_dt(v)
    except Exception:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field {field} must be an ISO 8601 timestamp"
        )
    return v


def pagination_args():
    """limit/offset query parameters with scaffold defaults (10 / 0, 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset
