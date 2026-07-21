"""Standard response envelope helpers (PRD 2.2 / scaffold 1.0)."""
import random
import string
from flask import jsonify

from store import wall_now_iso, sort_key

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": wall_now_iso()}
    if extra:
        m.update(extra)
    return m


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


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta_extra


def list_response(entities, serializer, limit, offset):
    entities = sorted(entities, key=sort_key)
    page, meta_extra = paginate(entities, limit, offset)
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": [serializer(e) for e in page],
    }
    return jsonify(body), 200
