"""Standard response envelope (PRD §2.2 / SCAFFOLD §1.0).

success: { "meta": {api_request_id, api_request_timestamp, [pagination...]},
           "response_type": "object"|"array", "data": {...} }
error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""
import random
import string

from flask import jsonify

from db import store

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    # api_request_id starts with req_ (PRD §2.2)
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def ok_empty(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
