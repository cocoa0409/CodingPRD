"""Standard response-envelope helpers.

Envelope shape is fixed by SCAFFOLD.yaml §1.0 and PRD §2.2:

  success object: { "meta": {api_request_id, api_request_timestamp [, pagination]},
                    "response_type": "object" | "array", "data": {...} }
  error:          { "meta": {api_request_id, api_request_timestamp},
                    "response_type": "error",
                    "data": { "error_id": "...", "message": "..." } }

Timestamps are ISO 8601 UTC with three fractional digits.
api_request_id starts with "req_".
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso_millis(dt=None):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_millis(),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_array(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
