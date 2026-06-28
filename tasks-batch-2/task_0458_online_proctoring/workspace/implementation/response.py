"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from clock import now_iso_realish


def _request_id():
    # PRD §2.2: a server-generated unique identifier that starts with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # api_request_timestamp: ISO 8601 UTC with three fractional digits.
        "api_request_timestamp": now_iso_realish(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    """Build a success envelope.

    pagination, when provided, is a dict of {limit, offset, total_count,
    has_more} merged into meta (PRD §2.3).
    """
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, http_status):
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
