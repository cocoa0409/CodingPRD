"""Standard response envelope helpers."""
import secrets
import string
from flask import jsonify, request

from clock import clock


_ALPHABET = string.ascii_letters + string.digits


def gen_request_id() -> str:
    rand_part = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{rand_part}"


def _meta(extra: dict = None) -> dict:
    rid = getattr(request, "_api_request_id", None) or gen_request_id()
    request._api_request_id = rid
    m = {
        "api_request_id": rid,
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, http_status=200, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def ok_array(items, limit, offset, total_count, has_more, http_status=200):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
