import random
import string

from flask import jsonify

from store import now_iso, serialize


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def success_array(items, limit, offset, total):
    has_more = (offset + len(items)) < total
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(i) for i in items],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
