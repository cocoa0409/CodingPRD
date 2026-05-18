"""Response envelope helpers."""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    chars = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _now_iso_real() -> str:
    """Real wall-clock ISO 8601 UTC timestamp with 3 fractional digits.

    Used for the response envelope `api_request_timestamp` (which is the server's
    response time, not the logical simulated clock).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def make_meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_real(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data: dict, status: int = 200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_array(data: list, pagination: dict, status: int = 200):
    body = {
        "meta": make_meta(pagination),
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def ok_empty(status: int = 200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": {},
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
