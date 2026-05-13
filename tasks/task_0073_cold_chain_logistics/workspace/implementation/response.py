"""Response envelope helpers for the cold-chain-logistics API."""

from __future__ import annotations

import secrets
import string

from flask import jsonify

from clock import clock


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination=None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def object_response(data, status_code: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def array_response(data_list, *, limit: int, offset: int, total_count: int, status_code: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(data_list)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": data_list,
    }
    return jsonify(body), status_code


def error_response(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
