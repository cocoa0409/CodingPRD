"""Response envelope helpers (PRD §2.2 / SCAFFOLD §1.0)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    body = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + body


def now_iso():
    # ISO 8601 UTC with exactly three fractional digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
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
    resp = jsonify(body)
    return resp
