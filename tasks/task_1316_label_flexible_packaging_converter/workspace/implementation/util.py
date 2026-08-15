"""Payload parsing/validation and pagination helpers (PRD 2.3, 2.5)."""
from flask import request

from errors import ApiError

_INVALID = "ERR_INVALID_REQUEST"


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError(_INVALID, 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(_INVALID, 400, "Request body must be a JSON object")
        return data
    return {}


def reject_unknown(data, allowed):
    """No unknown payload fields may appear (PRD 2.5 step 4)."""
    extra = [k for k in data if k not in allowed]
    if extra:
        raise ApiError(
            _INVALID, 400, "Unknown payload field(s): " + ", ".join(sorted(extra))
        )


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError(_INVALID, 400, f"Missing required field: {field}")
    return data[field]


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(_INVALID, 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError(_INVALID, 400, f"Field {field} must be a string")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError(_INVALID, 400, f"Field {field} must be a boolean")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(_INVALID, 400, f"Field {field} must be a number")
    return v


def as_enum(v, field, choices):
    if not isinstance(v, str) or v not in choices:
        raise ApiError(
            _INVALID, 400, f"Field {field} must be one of {sorted(choices)}"
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
            raise ApiError(_INVALID, 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(_INVALID, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(_INVALID, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(_INVALID, 400, "offset must be >= 0")
    return limit, offset
