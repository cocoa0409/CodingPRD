"""Response envelope helpers."""
from __future__ import annotations
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _now_iso_ms() -> str:
    # ISO 8601 UTC with three fractional digits and trailing Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }


def success(data, status: int = 200, response_type: str = "object", pagination: dict | None = None):
    meta = _meta_base()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_object(data, status: int = 200):
    return success(data, status=status, response_type="object")


def success_array(data: list, pagination: dict, status: int = 200):
    return success(data, status=status, response_type="array", pagination=pagination)


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
