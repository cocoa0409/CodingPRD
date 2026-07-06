"""Shared view helpers: serialization, pagination, body parsing, validation."""
from flask import request

from errors import ApiError

# Computed fields are attached to each serialized record by the route layer
# via recompute functions; only the internal _seq is stripped here.
_INTERNAL = {"_seq"}


def serialize(rec):
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def serialize_list(recs):
    return [serialize(r) for r in recs]


def get_json():
    """Return the JSON body as a dict (empty dict if none)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def parse_pagination():
    """Return (limit, offset) validated against bounds."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset out of bounds")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation order, slice, return (page, pagination_meta)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def require_int(value, field, positive=False, non_negative=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if positive and value <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be positive" % field)
    if non_negative and value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be non-negative" % field)
    return value
