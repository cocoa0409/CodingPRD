"""Standard response envelope helpers (PRD §2.2).

success: { "meta": {...}, "response_type": "object"|"array", "data": {} }
error:   { "meta": {...}, "response_type": "error", "data": {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _iso_now_ms():
    # Wall-clock UTC timestamp with exactly three fractional digits (response meta).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _iso_now_ms(),
    }


def success(data, status=200, response_type="object", pagination=None):
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


def success_object(data, status=200):
    return success(data, status=status, response_type="object")


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body
