"""Response envelope helpers and pagination."""
import random
import string
from flask import jsonify, request

from db import now_iso
from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination():
    """Read limit/offset query params, clamped to spec bounds."""
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        if limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at asc (stable by creation seq), apply offset/limit."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
