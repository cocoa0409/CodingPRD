"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success envelope:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [list-only: "limit","offset","total_count","has_more"] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

The api_request_timestamp is a real ISO 8601 UTC wall-clock timestamp with three
fractional digits (it is a server-generated request stamp, distinct from the
logical clock that drives business time).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    millis = dt.microsecond // 1000
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, millis
    )


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def success(data, status=200, pagination=None):
    """Build a success response. response_type derived from data shape."""
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
