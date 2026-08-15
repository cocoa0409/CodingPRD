"""Parsing, validation, rounding, and pagination helpers."""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import LOGICAL_CLOCK
from errors import ApiError


# ---------------------------------------------------------------------------
# Dates and times
# ---------------------------------------------------------------------------

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


def logical_now_dt():
    """Current logical clock as an aware datetime."""
    return parse_dt(LOGICAL_CLOCK["current"])


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Decimal helpers and rounding (PRD 2.8)
# ---------------------------------------------------------------------------

def D(x):
    """Lossless Decimal conversion for ints/floats/strings."""
    return Decimal(str(x))


def round_half_up(value, places):
    """Round a Decimal half-up to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def round2f(value):
    """Round half-up to 2dp, returned as float."""
    return float(round_half_up(value, 2))


def round4f(value):
    """Round half-up to 4dp, returned as float."""
    return float(round_half_up(value, 4))


def half_star(quotient):
    """Snap a Decimal quotient to the half-star grid: floor(2x + 0.5) / 2."""
    floored = math.floor(2 * quotient + Decimal("0.5"))
    return floored / 2


# ---------------------------------------------------------------------------
# Request body helpers — all raise ERR_INVALID_REQUEST (400) on bad shape
# ---------------------------------------------------------------------------

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


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a number")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an array")
    return v


def as_iso_dt(v, field):
    as_str(v, field)
    try:
        parse_dt(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp"
        )
    return v


def as_int_range(v, field, lo, hi):
    v = as_int(v, field)
    if v < lo or v > hi:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be between {lo} and {hi}"
        )
    return v


def as_non_negative_int(v, field):
    v = as_int(v, field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= 0")
    return v


def as_positive_int(v, field):
    v = as_int(v, field)
    if v <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be > 0")
    return v


def as_positive_num(v, field):
    v = as_num(v, field)
    if v <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be > 0")
    return v


def as_non_negative_num(v, field):
    v = as_num(v, field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= 0")
    return v


def filter_arg(name):
    """Optional exact-match query filter value (None when absent/empty)."""
    v = request.args.get(name)
    return v if v not in (None, "") else None


def apply_filters(rows, filters):
    """filters: list of (field, value); None values are skipped."""
    for field, value in filters:
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return rows


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
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset
