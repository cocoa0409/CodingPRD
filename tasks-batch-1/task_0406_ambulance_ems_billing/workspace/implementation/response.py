"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD §1.0).

Success envelope:
    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
                [list-only: "limit", "offset", "total_count", "has_more"] },
      "response_type": "object" | "array",
      "data": {} | [] }

Error envelope:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id", "message" } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success(data, status=200, list_meta=None):
    """Build a success envelope.

    data: dict (object) or list (array).
    list_meta: optional dict with limit/offset/total_count/has_more for lists.
    """
    meta = _base_meta()
    response_type = "array" if isinstance(data, list) else "object"
    if list_meta is not None:
        meta.update(list_meta)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
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
