"""Standard response envelope (PRD §2.2).

Success:
  { "meta": { "api_request_id", "api_request_timestamp", [pagination...] },
    "response_type": "object" | "array", "data": ... }
Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _gen_request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _now_iso_millis():
    # ISO 8601 UTC timestamp with exactly three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso_millis(),
    }


def success(data, status=200, pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
