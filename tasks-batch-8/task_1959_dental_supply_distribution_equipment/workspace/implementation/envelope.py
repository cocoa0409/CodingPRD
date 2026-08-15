"""Standard response envelope helpers (PRD section 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _wall_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, message, status):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
