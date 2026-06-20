"""Standard response envelope per PRD §2.2 and scaffold §1.0.

success: { "meta": {...}, "response_type": "object"|"array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id": ..., "message": ... } }
"""
import random
import string
from flask import jsonify

from db import now_iso


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination is not None:
        # limit/offset/total_count/has_more live inside meta for list endpoints
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error(api_error):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
