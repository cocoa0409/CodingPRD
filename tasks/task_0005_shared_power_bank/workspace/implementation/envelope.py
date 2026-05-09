from flask import jsonify
from clock import clock
from common import new_request_id, fmt_ts
from errors import APIError


def _meta(extra: dict | None = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, http_status: int = 200, response_type: str = "object", pagination: dict | None = None):
    meta = _meta(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def created(data):
    return success(data, http_status=201, response_type="object")


def listed(items, limit: int, offset: int, total_count: int):
    has_more = (offset + limit) < total_count
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, http_status=200, response_type="array", pagination=pag)


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
