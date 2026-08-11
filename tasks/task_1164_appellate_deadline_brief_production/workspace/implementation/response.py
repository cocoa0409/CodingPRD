"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""
from flask import jsonify

from db import new_request_id, wall_now_iso


def _meta(include_pagination=False, limit=None, offset=None, total_count=None, has_more=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = has_more
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
        "meta": _meta(True, limit, offset, total_count, has_more),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
