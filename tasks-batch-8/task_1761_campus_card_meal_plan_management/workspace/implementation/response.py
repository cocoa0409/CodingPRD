"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from flask import jsonify

from db import store


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def success(data, status=200, pagination=None):
    m = meta()
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    body = {
        "meta": m,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
