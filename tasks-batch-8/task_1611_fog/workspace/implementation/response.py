"""Standard response envelope helpers (PRD §2.2 / scaffold §1.0)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _wall_timestamp():
    """ISO 8601 UTC wall-clock timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
