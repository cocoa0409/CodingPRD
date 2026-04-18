"""Standard response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify

from clock import get_now


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _wall_clock_iso() -> str:
    """Server wall clock timestamp (real-time), ISO 8601 UTC with 3 fractional digits."""
    now = datetime.now(timezone.utc)
    # Truncate to ms precision
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"


def make_meta(pagination: dict = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_clock_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, response_type: str = "object", status: int = 200, pagination: dict = None):
    body = {
        "meta": make_meta(pagination=pagination),
        "response_type": response_type,
        "data": data,
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
