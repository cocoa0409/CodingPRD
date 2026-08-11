"""Standard response envelope helpers, matching SCAFFOLD response_envelope:
success: { meta: {api_request_id, api_request_timestamp, [pagination...]},
           response_type: "object"|"array", data: ... }
error:   { meta: {api_request_id, api_request_timestamp},
           response_type: "error", data: {error_id, message} }
"""
import random
import string

from flask import jsonify

from clock import now, iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(page_meta), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
