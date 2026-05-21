"""Response envelope helpers."""
import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from flask import jsonify


def _now_iso8601_ms() -> str:
    """ISO 8601 UTC with millisecond precision, Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def make_meta(pagination: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso8601_ms(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data: Dict[str, Any], status: int = 200):
    body = {
        "meta": make_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(items, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": make_meta(
            pagination={
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def success_empty(status: int = 204):
    # 204 No Content: no body.
    return ("", status)
