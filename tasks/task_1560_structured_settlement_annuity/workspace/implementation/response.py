"""Response envelope helpers, matching SCAFFOLD response_envelope exactly:

success: { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": { ... }, "response_type": "error",
           "data": { "error_id": "ERR_XXX", "message": "..." } }
pagination fields on list responses (in meta): limit, offset, total_count, has_more
"""

import random
import string
from flask import jsonify
from db import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _meta(include_pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
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


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
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
