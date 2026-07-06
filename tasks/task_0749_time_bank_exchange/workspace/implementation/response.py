"""Response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


def _api_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _api_request_timestamp() -> str:
    now = datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def envelope_object(data, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _api_request_id(),
            "api_request_timestamp": _api_request_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def envelope_array(items, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + limit) < total_count
    body = {
        "meta": {
            "api_request_id": _api_request_id(),
            "api_request_timestamp": _api_request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def envelope_error(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _api_request_id(),
            "api_request_timestamp": _api_request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
