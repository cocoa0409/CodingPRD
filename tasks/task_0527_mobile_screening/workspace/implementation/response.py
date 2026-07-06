"""Standard response envelope helpers (PRD §2.2)."""
import random
import string
from flask import jsonify
from clock import clock

_ALNUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


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
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
