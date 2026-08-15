"""Parsing, validation, rounding, and pagination helpers.

Error IDs come from the PRD error catalogue: ERR_INVALID_REQUEST (400) for
missing/wrong-typed/out-of-range scalars, ERR_INVALID_ENUM (400) for enum
values outside the declared set.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC default)."""
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
    """Parse a strict YYYY-MM-DD date string into a date."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ValueError("not a YYYY-MM-DD date string")
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def parse_ym(value):
    """Parse a strict YYYY-MM month string."""
    if not isinstance(value, str) or not _MONTH_RE.match(value.strip()):
        raise ValueError("not a YYYY-MM month string")
    y, m = int(value[:4]), int(value[5:7])
    if m < 1 or m > 12:
        raise ValueError("month out of range")
    return y, m


def round_half_up_cents(value):
    """Round a Decimal to the nearest integer cent, half-up (PRD 2.9)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_tenth_hour(value):
    """Round a Decimal to the nearest tenth of an hour (PRD 2.9)."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def dec(value):
    """Exact Decimal for a JSON number."""
    return Decimal(str(value))


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
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field
        )
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % field
        )
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field
        )
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field %s must be a number" % field
        )
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % field
        )
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            "ERR_INVALID_ENUM",
            400,
            "Field %s must be one of %s" % (field, sorted(choices)),
        )
    return v


def as_iso_dt(v, field):
    """Validate an ISO 8601 timestamp; returns (raw_string, parsed_datetime)."""
    as_str(v, field)
    try:
        dt = parse_dt(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field %s must be an ISO 8601 timestamp" % field,
        )
    return v, dt


def as_date(v, field):
    """Validate a YYYY-MM-DD date; returns (raw_string, parsed_date)."""
    as_str(v, field)
    try:
        d = parse_ymd(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field %s must be a YYYY-MM-DD date" % field,
        )
    return v, d


def as_month(v, field):
    """Validate a YYYY-MM month identifier."""
    as_str(v, field)
    try:
        parse_ym(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field %s must be a YYYY-MM month identifier" % field,
        )
    return v


def as_version(v, field):
    if not _is_int(v):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field %s must be an integer version" % field,
        )
    return v


def pagination_args():
    """limit/offset query parameters (PRD 2.3: default 10/0, limit in 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "limit must be an integer"
            )
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "offset must be an integer"
            )
    if limit < 1 or limit > 100:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100"
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset
