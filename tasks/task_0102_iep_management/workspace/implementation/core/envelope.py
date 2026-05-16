"""Response envelope helpers — exact format from SCAFFOLD §1.0 / PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{rand}"


def _timestamp() -> str:
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination=None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(data_list, *, limit: int, offset: int, total_count: int, http_status: int = 200):
    has_more = (offset + len(data_list)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination=pagination),
        "response_type": "array",
        "data": data_list,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
