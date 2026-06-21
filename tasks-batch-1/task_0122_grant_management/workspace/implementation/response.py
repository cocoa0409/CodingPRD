"""Standard response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601,
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error envelope:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # PRD §2.2: server-generated unique id starting with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso():
    # PRD §2.4 / §2.2: ISO 8601 UTC with exactly three fractional digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success(data, status=200, pagination=None):
    """Build a success response.

    data: a dict (object) or list (array). response_type is derived from the
    Python type so list endpoints get "array" and singletons get "object".
    pagination: optional dict with limit/offset/total_count/has_more merged
    into meta for list endpoints (PRD §2.3).
    """
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
