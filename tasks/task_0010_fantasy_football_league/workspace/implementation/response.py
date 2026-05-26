"""Standard response envelope helpers."""
from flask import jsonify

from db import new_request_id, now_iso


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, code=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = code
    return resp


def success_object(data, code=200):
    return success(data, code=code, response_type="object")


def success_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(extra),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
