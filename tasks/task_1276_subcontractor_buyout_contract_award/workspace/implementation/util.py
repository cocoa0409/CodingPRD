"""Parsing, validation, rounding, and pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError


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


def round_half_up_cents(value):
    """Round a Decimal to the nearest integer cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 422, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a string")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a number")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_VALIDATION", 422, f"Field {field} must be one of {sorted(choices)}"
        )
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an array")
    return v


def as_iso_dt(v, field):
    as_str(v, field)
    try:
        parse_dt(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an ISO 8601 timestamp")
    return v


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
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def basis_arg():
    basis = request.args.get("basis", "PROVISIONAL")
    if basis not in ("PROVISIONAL", "FINAL"):
        raise ApiError("ERR_VALIDATION", 422, "basis must be PROVISIONAL or FINAL")
    return basis
