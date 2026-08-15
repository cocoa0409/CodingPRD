"""Parsing, validation, rounding, and pagination helpers.

Body-shape failures are ERR_INVALID_REQUEST (400) per the scaffold error
catalog. All rounding is round-half-up via Decimal (PRD section 2.6).
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

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


def parse_ymd(value):
    """Parse a strict YYYY-MM-DD date string into a date."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def dec(value):
    """Exact Decimal from a JSON number (avoids binary float artifacts)."""
    return Decimal(str(value))


def round_cents(value):
    """Round a Decimal to the nearest integer cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_mbf(value):
    """Round a Decimal to 3 decimal places, half-up; returned as float."""
    return float(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def round_pct2(value):
    """Round a Decimal to 2 decimal places, half-up; returned as float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _bad(field, msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"{field}: {msg}")


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Request body must be valid JSON"
            )
        if not isinstance(data, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Request body must be a JSON object"
            )
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        _bad(field, "missing required field")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_str(v, field):
    if not isinstance(v, str) or not v:
        _bad(field, "must be a non-empty string")
    return v


def as_int(v, field, positive=False):
    if not _is_int(v):
        _bad(field, "must be an integer")
    if positive and v <= 0:
        _bad(field, "must be a positive integer")
    return v


def as_num(v, field, positive=False, non_negative=False):
    if not _is_num(v):
        _bad(field, "must be a number")
    if positive and v <= 0:
        _bad(field, "must be a positive number")
    if non_negative and v < 0:
        _bad(field, "must be a non-negative number")
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        _bad(field, f"must be one of {sorted(choices)}")
    return v


def as_list(v, field, non_empty=False):
    if not isinstance(v, list):
        _bad(field, "must be an array")
    if non_empty and len(v) == 0:
        _bad(field, "must be a non-empty array")
    return v


def as_iso_dt(v, field):
    if not isinstance(v, str):
        _bad(field, "must be an ISO 8601 timestamp string")
    try:
        parse_dt(v)
    except Exception:
        _bad(field, "must be an ISO 8601 timestamp")
    return v


def as_ymd(v, field):
    if not isinstance(v, str):
        _bad(field, "must be a YYYY-MM-DD date string")
    try:
        parse_ymd(v)
    except Exception:
        _bad(field, "must be a YYYY-MM-DD date")
    return v


def pagination_args():
    """limit/offset query parameters (defaults 10 / 0; limit within 1..100)."""
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
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100"
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset
