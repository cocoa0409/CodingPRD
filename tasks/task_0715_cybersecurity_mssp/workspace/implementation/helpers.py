"""Request parsing, pagination, validation helpers."""
from flask import request

from errors import ApiError
from store import parse_iso


def get_json_body():
    """Return the request JSON body as a dict, or raise ERR_INVALID_REQUEST if malformed."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def require_number(body, field, minimum=None, maximum=None, exclusive_min=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be > {exclusive_min}.")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be <= {maximum}.")
    return v


def require_int(body, field, minimum=None, exclusive_min=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be > {exclusive_min}.")
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def require_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO-8601 string.")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO-8601 datetime.")


def parse_pagination():
    """Parse and validate limit/offset query params. Returns (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be in [1, 100].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at asc (seq tiebreak), apply window. Returns (page, total)."""
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
