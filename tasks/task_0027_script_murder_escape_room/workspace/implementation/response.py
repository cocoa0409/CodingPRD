"""Response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso() -> str:
    # ISO 8601 UTC with three fractional digits and trailing Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}" + "Z"


def success_object(data, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def success_array(data_list, limit: int, offset: int, total_count: int, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(data_list)) < total_count,
        },
        "response_type": "array",
        "data": data_list,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
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
