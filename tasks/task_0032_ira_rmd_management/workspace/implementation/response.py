"""Standard response envelope helpers per PRD §2.2."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


_REQ_ID_ALPHABET = string.ascii_letters + string.digits


def _make_request_id() -> str:
    body = "".join(secrets.choice(_REQ_ID_ALPHABET) for _ in range(20))
    return f"req_{body}"


def _make_timestamp() -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(now.microsecond / 1000):03d}Z"


def _base_meta() -> dict:
    return {
        "api_request_id": _make_request_id(),
        "api_request_timestamp": _make_timestamp(),
    }


def success_object(data, status_code: int = 200):
    """Single-resource 2xx response."""
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def success_array(data_list, limit: int, offset: int, total_count: int, status_code: int = 200):
    """List response with pagination fields in meta."""
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data_list,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
