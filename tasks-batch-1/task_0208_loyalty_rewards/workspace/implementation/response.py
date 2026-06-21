"""Standard response envelope helpers (PRD §2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def now_iso():
    """Wall-clock ISO 8601 UTC timestamp with exactly three fractional digits + 'Z'.

    Used for the response envelope's api_request_timestamp and for the
    created_at / updated_at stamps of resources (which reflect real time of
    write, independent of the logical business clock).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
