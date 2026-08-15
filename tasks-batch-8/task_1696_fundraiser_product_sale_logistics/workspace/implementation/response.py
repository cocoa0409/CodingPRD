"""Standard response envelope helpers per PRD §2.2 / §2.3."""

import secrets
import string

from flask import jsonify

from db import clock, _format_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(include_pagination=False, limit=None, offset=None, total_count=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _format_iso(clock.now()),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = (offset + limit) < total_count
    return m


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


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
