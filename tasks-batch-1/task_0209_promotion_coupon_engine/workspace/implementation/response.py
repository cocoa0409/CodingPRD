"""Standard response envelope helpers (PRD §2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_ms():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """Build a single-object or empty-object success response.

    `data` may be a dict (response_type=object) or None (empty object payload).
    """
    response_type = "object"
    payload = data if data is not None else {}
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": payload,
    }
    return jsonify(body), status


def success_null(status=200, pagination=None):
    """Build a success response whose `data` is literal JSON null (PRD §3.9:
    an auto-apply with no candidate returns "a 200 response with null data").
    """
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": None,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    """Build an array success response with pagination meta."""
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


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
