"""Standard response envelope helpers (PRD §2.2)."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


def _now_iso() -> str:
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{body}"


def success_response(data, http_status=200, response_type=None, pagination=None):
    """Build a standard success envelope.

    pagination dict keys: limit, offset, total_count, has_more.
    """
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
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
