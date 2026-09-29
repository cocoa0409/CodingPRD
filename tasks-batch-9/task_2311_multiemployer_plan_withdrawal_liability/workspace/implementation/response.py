"""Standard response envelope (PRD §2.2)."""

import random
import string

from flask import jsonify

from clockutil import real_now_str

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": real_now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def obj(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return obj(data, 201)


def arr(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), 200


def error(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
