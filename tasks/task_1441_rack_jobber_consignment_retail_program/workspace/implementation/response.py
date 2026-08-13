"""Standard response envelope helpers (PRD Section 2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              ["limit", "offset", "total_count", "has_more" for lists] },
    "response_type": "object" | "array",
    "data": {...} | [...] }

Error envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from db import store


def _request_id():
    # api_request_id is a server-generated unique id that starts with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    # The logical clock governs every recorded timestamp (PRD Section 2.6).
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, http_status=200, is_list=False, pagination=None):
    """Build a 2xx envelope.

    pagination, when provided, is {limit, offset, total_count, has_more}
    merged into meta for list endpoints (PRD Sections 2.2 / 2.3).
    """
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
