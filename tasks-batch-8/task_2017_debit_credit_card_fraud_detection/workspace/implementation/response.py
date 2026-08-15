"""Standard response envelope helpers."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _request_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status_code: int = 200, pagination: dict | None = None):
    """Build a success envelope.

    pagination: optional dict with keys limit/offset/total_count/has_more for lists.
    """
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def error(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
