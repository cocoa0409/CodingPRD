"""Standard response envelope helpers."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_millis():
    # ISO 8601 UTC with three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_millis(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, http_status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    from errors import ERROR_CATALOG

    resp = jsonify(body)
    resp.status_code = ERROR_CATALOG.get(error_id, 400)
    return resp
