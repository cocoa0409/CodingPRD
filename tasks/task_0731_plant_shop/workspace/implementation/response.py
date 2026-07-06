"""Standard response envelope per PRD §2.2."""
from flask import jsonify
from db import new_request_id
from clock import iso_now


def _meta(pagination: dict = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, code: int = 200, pagination: dict = None):
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def created(data, pagination: dict = None):
    return ok(data, 201, pagination)


def ok_list(items, code: int = 200, limit: int = 10, offset: int = 0, total_count: int = 0):
    has_more = offset + len(items) < total_count
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), code


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
