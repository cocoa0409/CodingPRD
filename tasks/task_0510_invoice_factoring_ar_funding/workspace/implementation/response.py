"""Standard response-envelope helpers (§1.0 / PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """Single-object or array success envelope.

    pagination, when supplied, is a dict with limit/offset/total_count/has_more
    and the response_type becomes "array".
    """
    if pagination is not None:
        body = {
            "meta": _meta(pagination),
            "response_type": "array",
            "data": data,
        }
    else:
        body = {
            "meta": _meta(),
            "response_type": "object",
            "data": data if data is not None else {},
        }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_envelope(error_id, message, http_status):
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
