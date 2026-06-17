"""Standard response envelope helpers (PRD section 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.2/2.4)."""
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
    """Single object or array success envelope.

    response_type is "array" when data is a list, else "object".
    Pagination bookkeeping (limit/offset/total_count/has_more) lives in meta.
    """
    is_array = isinstance(data, list)
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
