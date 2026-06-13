"""Standard response envelope helpers.

Envelope structure is read verbatim from SCAFFOLD.yaml §1.0 response_envelope
and PRD §2.2 (API Response Structure):

  success:  { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
              "response_type": "object"|"array", "data": {} | [] }
  error:    { "meta": { "api_request_id", "api_request_timestamp" },
              "response_type": "error",
              "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso():
    # ISO 8601 UTC with exactly three fractional digits (PRD §2.2 / §2.4).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _request_id():
    # Server-generated unique id that starts with "req_" (PRD §2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, http_status):
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
