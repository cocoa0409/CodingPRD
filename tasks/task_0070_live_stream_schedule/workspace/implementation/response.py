"""Standard response envelope helpers — see PRD §2.2."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import format_iso


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    # The request timestamp uses real (host) wall-clock time, not the simulated clock.
    # It is purely a transport-level annotation per PRD §2.2 and is not subject to /_clock control.
    return format_iso(datetime.now(timezone.utc))


def _meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, http_status: int = 200, pagination: dict | None = None,
            response_type: str | None = None):
    """Return a Flask response with the success envelope.

    response_type defaults to "array" when data is a list, else "object".
    """
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"

    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error(error_id: str, message: str, http_status: int):
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
