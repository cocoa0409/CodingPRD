"""Standard success / error response envelope."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _iso_now() -> str:
    # ISO 8601 UTC with three fractional digits, trailing Z.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(
    data: Any,
    *,
    status: int = 200,
    response_type: str = "object",
    pagination: dict | None = None,
):
    meta: dict[str, Any] = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _iso_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _iso_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
