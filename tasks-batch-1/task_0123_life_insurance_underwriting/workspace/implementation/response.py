"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [list-only: "limit","offset","total_count","has_more"] },
    "response_type": "object" | "array",
    "data": {...} | [...] }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
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
