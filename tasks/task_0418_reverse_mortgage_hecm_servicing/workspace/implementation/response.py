"""Standard response-envelope helpers (§2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, list_meta=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(list_meta),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, http_status, message):
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
