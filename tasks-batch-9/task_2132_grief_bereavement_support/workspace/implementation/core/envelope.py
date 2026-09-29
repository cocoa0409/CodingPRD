"""Standard response envelope, pagination and error rendering."""

import random
import string

from flask import jsonify, request

from .errors import ApiError
from .store import store

ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items):
    """Apply limit/offset from the query string; returns (page, limit, offset, total)."""
    limit = _int_param("limit", LIMIT_DEFAULT)
    offset = _int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def listing(items, serializer=None):
    page, limit, offset, total = paginate(items)
    data = [serializer(r) for r in page] if serializer else page
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), 200
