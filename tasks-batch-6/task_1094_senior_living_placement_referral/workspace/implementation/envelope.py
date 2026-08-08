"""Response envelope helpers."""
import random
import string
from flask import jsonify

import store


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, limit, offset, total_count, has_more):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def ok_array(items):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
