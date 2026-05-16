"""Response envelope helpers."""

import secrets
import string
from flask import jsonify

from clock import clock


def _generate_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination: dict = None) -> dict:
    m = {
        "api_request_id": _generate_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_array(items, pagination_meta: dict, status=200):
    body = {
        "meta": _meta(pagination_meta),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
