"""Standard response envelope (PRD §2.2, scaffold §1.0 — EMIT VERBATIM).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import format_iso


def _request_id():
    body = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + body


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
