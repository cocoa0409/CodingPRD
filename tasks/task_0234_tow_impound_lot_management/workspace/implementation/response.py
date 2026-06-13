"""Standard response envelope (PRD §2.2). Shape:
{ "meta": {api_request_id, api_request_timestamp, [pagination]},
  "response_type": "object"|"array"|"error", "data": {...} }"""
import random
import string

from flask import jsonify

from clock import iso, now


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


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(items, limit, offset, total_count, status=200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
