"""Shared route plumbing: JSON body, pagination, sorted list responses."""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from response import success_list

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def body():
    """Request JSON object; missing body counts as {}. Non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _parse_int_arg(raw, default, lo, hi):
    if raw is None:
        return default
    try:
        v = int(str(raw))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid pagination parameter")
    return max(lo, min(hi, v))


def paginate(records, serializer):
    """Sort by created_at ASC (insertion order tiebreak), apply limit/offset,
    and wrap in the list envelope."""
    limit = _parse_int_arg(request.args.get("limit"), DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset_raw = request.args.get("offset")
    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(str(offset_raw))
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid pagination parameter")
        offset = max(0, offset)
    rows = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % f)


def coerce_version(value, field_name):
    """OCC fields may arrive as int or numeric string."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid %s" % field_name)
