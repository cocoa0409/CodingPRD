"""Standard response envelope helpers.

Envelope shape is fixed by SCAFFOLD.yaml section 1.0 / PRD section 2.2:

  success: { "meta": {"api_request_id","api_request_timestamp", <pagination?>},
             "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {"api_request_id","api_request_timestamp"},
             "response_type": "error",
             "data": {"error_id","message"} }

Pagination fields (limit, offset, total_count, has_more) live INSIDE meta on
list responses (PRD 2.3).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

# api_request_timestamp uses the real wall-clock UTC of the request, with three
# fractional digits — this is the request-processing time, distinct from the
# logical business clock used for temporal rules.


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _request_timestamp():
    return iso_millis(datetime.now(timezone.utc))


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
