"""Response envelope helpers (success, error, pagination)."""
from flask import jsonify, request

from errors import ApiError, bad_request
from util import new_request_id, fmt_iso
from datetime import datetime, timezone


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, response_type="object", pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(payload), status


def ok_list(items, pagination):
    return ok(items, status=200, response_type="array", pagination=pagination)


def error_response(err):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), err.http_status


# ---------------------------------------------------------------------------
# Pagination parsing (limit / offset, defaults 10 / 0, min 1, max 100)
# ---------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1:
            raise bad_request("limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise bad_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Slice a pre-sorted list and build the pagination meta block."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
