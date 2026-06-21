"""Standard response envelope helpers (PRD §2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # Server-generated unique identifier that starts with "req_" (PRD §2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso():
    # ISO 8601 UTC timestamp with three fractional digits (PRD §2.2 / §2.4).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """Wrap a single object or list in the standard success envelope.

    response_type is "array" for lists, "object" otherwise (PRD §2.2).
    Pagination fields (limit, offset, total_count, has_more) live in meta for
    list endpoints (PRD §2.2 / §2.3).
    """
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    """Standard error envelope (PRD §2.2)."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
