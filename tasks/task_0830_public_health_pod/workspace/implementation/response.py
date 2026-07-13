"""Standard response envelope helpers (PRD 2.2, SCAFFOLD.yaml response_envelope)."""
import random
import string

from flask import jsonify

from timeutil import format_iso8601, now


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso8601(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def success_array(items, limit, offset, total_count, http_status=200):
    has_more = offset + len(items) < total_count
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
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
