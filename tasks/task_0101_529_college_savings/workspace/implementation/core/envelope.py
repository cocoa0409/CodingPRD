"""Response envelope helpers. Per PRD §2.2 and SCAFFOLD response_envelope."""

from flask import jsonify
from core.store import gen_id, gen_request_id
from core.clock import CLOCK
from core.errors import APIError


def _meta(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": CLOCK.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(data, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + len(data)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err: APIError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
