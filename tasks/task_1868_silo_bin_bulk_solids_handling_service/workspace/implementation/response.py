"""Standard response envelope helpers, per SCAFFOLD.yaml §1.0 and PRD §2.2."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso() -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(include_pagination: bool = False, limit=None, offset=None,
          total_count=None, has_more=None) -> dict:
    m = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
    return m


def success_object(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(include_pagination=True, limit=limit, offset=offset,
                      total_count=total_count, has_more=has_more),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
