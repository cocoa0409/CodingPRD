"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _meta(include_pagination=False, limit=None, offset=None, total_count=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if include_pagination:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + limit) < total_count
    return meta


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta(True, limit, offset, total_count),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
