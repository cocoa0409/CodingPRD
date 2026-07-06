"""Response envelope helpers."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_ms():
    # ISO 8601 UTC with exactly three fractional digits.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(chars) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
