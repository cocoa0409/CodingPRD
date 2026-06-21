"""Response envelope helpers, matching SCAFFOLD §1.0 / PRD §2.2 verbatim.

Success object:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              (list endpoints add limit/offset/total_count/has_more) },
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso_ms():
    """ISO 8601 UTC timestamp with exactly three fractional digits, Z suffix."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_ms(),
    }


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    return resp
