"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {} }

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
    # "req_" followed by random alphanumerics (PRD §2.2).
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def now_iso_millis():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.2/§2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_millis(),
    }


def success(data, status=200, response_type="object"):
    body = {
        "meta": _base_meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def success_object(data, status=200):
    return success(data, status=status, response_type="object")


def success_list(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
