"""Request body validation helpers (priority 29: ERR_INVALID_REQUEST)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def _bad(field: str, why: str):
    raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}': {why}", 400)


def body() -> dict:
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(data: dict, field: str, pattern: str = None, allow_empty: bool = False) -> str:
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, "required string")
    if not allow_empty and v == "":
        _bad(field, "must be non-empty")
    if pattern is not None and re.fullmatch(pattern, v) is None:
        _bad(field, f"must match pattern {pattern}")
    return v


def opt_str(data: dict, field: str, default=None, pattern: str = None,
            allow_empty: bool = True):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    if not allow_empty and v == "":
        _bad(field, "must be non-empty")
    if pattern is not None and re.fullmatch(pattern, v) is None:
        _bad(field, f"must match pattern {pattern}")
    return v


def req_int(data: dict, field: str, min_v=None, max_v=None) -> int:
    v = data.get(field)
    if not _is_int(v):
        _bad(field, "required integer")
    if min_v is not None and v < min_v:
        _bad(field, f"must be >= {min_v}")
    if max_v is not None and v > max_v:
        _bad(field, f"must be <= {max_v}")
    return v


def opt_int(data: dict, field: str, default=None, min_v=None, max_v=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_int(v):
        _bad(field, "must be an integer")
    if min_v is not None and v < min_v:
        _bad(field, f"must be >= {min_v}")
    if max_v is not None and v > max_v:
        _bad(field, f"must be <= {max_v}")
    return v


def req_num(data: dict, field: str) -> Decimal:
    v = data.get(field)
    if not _is_num(v):
        _bad(field, "required number")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        _bad(field, "must be a valid number")


def opt_num(data: dict, field: str, default=None, min_v=None, max_v=None) -> Decimal:
    v = data.get(field)
    if v is None:
        return default
    if not _is_num(v):
        _bad(field, "must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        _bad(field, "must be a valid number")
    if min_v is not None and d < Decimal(str(min_v)):
        _bad(field, f"must be >= {min_v}")
    if max_v is not None and d > Decimal(str(max_v)):
        _bad(field, f"must be <= {max_v}")
    return d


def req_bool(data: dict, field: str) -> bool:
    v = data.get(field)
    if not isinstance(v, bool):
        _bad(field, "required boolean")
    return v


def req_enum(data: dict, field: str, choices) -> str:
    v = data.get(field)
    if not isinstance(v, str) or v not in choices:
        _bad(field, f"must be one of {sorted(choices)}")
    return v


def opt_enum(data: dict, field: str, choices, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in choices:
        _bad(field, f"must be one of {sorted(choices)}")
    return v


def req_iso(data: dict, field: str):
    v = data.get(field)
    dt = db.parse_iso(v)
    if dt is None:
        _bad(field, "must be an ISO 8601 UTC date-time string")
    return dt


def _parse_int_param(raw: str, field: str) -> int:
    text = raw.strip()
    if not text.lstrip("+").isdigit():
        raise ApiError(ERR_INVALID_REQUEST, f"Query param '{field}' must be an integer", 400)
    return int(text)


def pagination_params():
    """Parse limit/offset query params (PRD 2.3: default 10/0, limit 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "Query param 'limit' must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "Query param 'offset' must be >= 0", 400)
    return limit, offset


def sort_and_page(records, serializer):
    """Sort by created_at ascending (stable by insertion seq), then paginate."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], limit, offset, total
