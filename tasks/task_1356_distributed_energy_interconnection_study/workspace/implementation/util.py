"""Request parsing, field validation, and pagination helpers.

Malformed inputs (missing required fields, invalid enum values, non-positive
amounts/capacities, out-of-range numbers) are rejected with ERR_INVALID_REQUEST
at HTTP 400, per this scaffold's error catalog.
"""
from flask import request

from clock import parse_iso
from errors import ApiError


def _invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def body():
    """JSON request body as a dict; {} when no body was sent."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            _invalid("Request body must be valid JSON")
        if not isinstance(data, dict):
            _invalid("Request body must be a JSON object")
        return data
    return {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _invalid(f"Field {field} is required and must be a string")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _invalid(f"Field {field} must be a string")
    return v


def req_enum(data, field, choices):
    v = data.get(field)
    if v not in choices:
        _invalid(f"Field {field} must be one of {sorted(choices)}")
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} is required and must be an integer")
    return v


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid(f"Field {field} must be an integer")
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid(f"Field {field} is required and must be a number")
    return v


def req_dt_str(data, field):
    """Required datetime field; returned raw (echoed verbatim) after a
    parseability check. Comparisons parse the raw string again."""
    v = data.get(field)
    if not isinstance(v, str):
        _invalid(f"Field {field} is required and must be an ISO 8601 timestamp")
    try:
        parse_iso(v)
    except Exception:
        _invalid(f"Field {field} must be a valid ISO 8601 timestamp")
    return v


def pagination_args():
    """limit/offset query parameters. Defaults 10 / 0; limit within [1, 100];
    offset >= 0 (scaffold response_envelope.pagination_defaults)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _invalid("limit must be an integer")
        if isinstance(limit, bool):
            _invalid("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _invalid("offset must be an integer")
    if limit < 1 or limit > 100:
        _invalid("limit must be between 1 and 100")
    if offset < 0:
        _invalid("offset must be >= 0")
    return limit, offset
