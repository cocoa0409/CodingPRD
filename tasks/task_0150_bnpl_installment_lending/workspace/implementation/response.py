"""Standard response envelope helpers (PRD §2.2).

Envelope (verbatim from SCAFFOLD §1.0):
  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object"|"array", "data": {} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(ALPHANUM, k=20))


def now_iso_millis():
    """ISO 8601 UTC timestamp with exactly three fractional digits and a 'Z'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_millis(),
    }


def success(data, status=200, pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
