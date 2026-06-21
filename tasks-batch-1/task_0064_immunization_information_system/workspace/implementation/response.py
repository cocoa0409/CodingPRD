import random
import string
from flask import jsonify
from store import STORE, now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(STORE.clock),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object"):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201, response_type="object")


def list_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
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


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
