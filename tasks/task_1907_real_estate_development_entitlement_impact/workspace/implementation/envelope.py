"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

import store


def _wall_timestamp() -> str:
    """api_request_timestamp: real wall-clock UTC, three fractional digits."""
    now = datetime.now(timezone.utc)
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{now.microsecond // 1000:03d}Z"


def _jsonable(value):
    """Convert Decimals to JSON numbers and datetimes to ISO strings."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return store.fmt_dt(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def success(data, status: int = 200, response_type: str = "object",
            pagination: dict = None):
    meta = {
        "api_request_id": store.request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    if pagination is not None:
        meta.update({
            "limit": pagination["limit"],
            "offset": pagination["offset"],
            "total_count": pagination["total_count"],
            "has_more": pagination["has_more"],
        })
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": _jsonable(data),
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, status: int):
    body = {
        "meta": {
            "api_request_id": store.request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def paginate(records, args):
    """Apply limit/offset query params; returns (page, pagination_meta).

    Defaults: limit=10 (min 1, max 100), offset=0. Sorted by created_at ASC
    (stable; insertion order breaks ties) before slicing.
    """
    from errors import ApiError, ERR_INVALID_REQUEST  # local import, no cycle

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if raw_limit is not None and str(raw_limit).strip() != str(limit):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    if raw_offset is not None and str(raw_offset).strip() != str(offset):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST,
                       "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)

    ordered = sorted(records, key=lambda r: r["created_at"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
