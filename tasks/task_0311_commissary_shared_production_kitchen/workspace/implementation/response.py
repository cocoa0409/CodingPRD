"""Standard response envelope helpers (PRD section 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, meta_extra=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def paginated(items, total_count, limit, offset, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=status, meta_extra=meta_extra)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
