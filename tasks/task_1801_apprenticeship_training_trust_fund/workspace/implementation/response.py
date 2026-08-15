"""Response envelope helpers — exact shape from SCAFFOLD §1.0 / PRD §2.2."""

import random
import string
from flask import jsonify

import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta(include_pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if include_pagination is not None:
        m["limit"] = include_pagination["limit"]
        m["offset"] = include_pagination["offset"]
        m["total_count"] = include_pagination["total_count"]
        m["has_more"] = include_pagination["has_more"]
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
