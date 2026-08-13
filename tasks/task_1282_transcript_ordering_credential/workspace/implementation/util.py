"""Parsing, validation, rounding, and pagination helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import parse_iso
from errors import ApiError


def round_half_up(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def reject_unknown_fields(data, allowed):
    """Unknown fields are shape violations (ERR_INVALID_REQUEST, 400)."""
    for key in data:
        if key not in allowed:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"Unknown field: {key}"
            )


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Missing required field: {field}"
        )
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a non-empty string")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be one of {sorted(choices)}",
        )
    return v


def as_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an array")
    return v


def as_iso_dt(v, field):
    as_str(v, field)
    try:
        parse_iso(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp"
        )
    return v


def as_iso_date(v, field):
    as_str(v, field)
    import datetime as _dt

    try:
        _dt.date.fromisoformat(v.strip())
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 date"
        )
    return v


def optional(data, field, default=None):
    v = data.get(field, default)
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
