"""Response envelope helpers matching PRD Section 2.2 / SCAFFOLD response_envelope."""

import random
import string
from flask import jsonify

from store import now, format_dt, clean
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_dt(now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": clean(data) if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err: ApiError):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def parse_pagination(args):
    """Parse limit/offset query params; raise ERR_VALIDATION on bad values."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_VALIDATION", "limit out of range")
    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (stable via _seq), slice, and build the meta block."""
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def list_response(items, limit, offset, serialize_fn):
    page, pag = paginate(items, limit, offset)
    return success([serialize_fn(r) for r in page], response_type="array",
                   status=200, pagination=pag)
