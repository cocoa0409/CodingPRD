import random
import string

from flask import jsonify

import util


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": util.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
