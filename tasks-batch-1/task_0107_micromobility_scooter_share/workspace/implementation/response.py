"""Standard response envelope helpers (PRD §2.2, scaffold §1.0 response_envelope).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [limit, offset, total_count, has_more on lists] },
    "response_type": "object" | "array", "data": {} }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import now_iso


def _request_id():
    # Server-generated unique id that starts with "req_" (PRD §2.2).
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        # Pagination fields live inside meta (PRD §2.3).
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
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
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
