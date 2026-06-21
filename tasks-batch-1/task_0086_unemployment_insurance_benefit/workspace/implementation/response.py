"""Standard response envelope (PRD §2.2, SCAFFOLD response_envelope).

success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object"|"array", "data": {...} }
error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""
import random
import string

from flask import jsonify

from clock import clock

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
