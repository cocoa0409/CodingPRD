"""Standard response envelope helpers.

Envelope shape is fixed by PRD §2.2 and SCAFFOLD §1.0:

  success: { "meta": { "api_request_id", "api_request_timestamp", <pagination?> },
             "response_type": "object"|"array", "data": {} }
  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    # PRD §2.2: api_request_id is a server-generated unique id starting with "req_".
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def now_iso_ms():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.2/§2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_ms(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """Single-object or arbitrary-data success response.

    response_type is "array" when data is a list, else "object" (PRD §2.2).
    """
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    """List response with pagination fields embedded in meta (PRD §2.3)."""
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


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
