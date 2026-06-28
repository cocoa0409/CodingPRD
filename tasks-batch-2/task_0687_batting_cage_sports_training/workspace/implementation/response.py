"""Response envelope helpers (PRD 2.2 / SCAFFOLD 1.0 response_envelope).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601[, pagination] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error", "data": { "error_id": ..., "message": ... } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # PRD 2.2: api_request_id starts with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _timestamp():
    # PRD 2.2: server-generated ISO 8601 UTC timestamp with three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }


def success(data, status=200, pagination=None):
    meta = _base_meta()
    response_type = "object"
    if pagination is not None:
        # List endpoints add pagination fields into meta. PRD 2.3.
        meta.update(pagination)
        response_type = "array"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, http_status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
