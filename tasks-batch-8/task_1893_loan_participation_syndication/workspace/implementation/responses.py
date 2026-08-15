"""Standard response envelope helpers (PRD section 2.2)."""
import json

from flask import Response

import errors
from store import now_ts, request_id


def _meta(pagination=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_ts(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def _send(payload, status):
    return Response(
        json.dumps(payload),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    return _send(
        {"meta": _meta(), "response_type": "object", "data": data},
        status,
    )


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return _send(
        {"meta": _meta(pagination), "response_type": "array", "data": items},
        200,
    )


def error_response(err):
    return _send(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        },
        err.http_status,
    )


def not_found_handler(_e):
    return error_response(errors.not_found("Resource not found"))


def method_not_allowed_handler(_e):
    return error_response(errors.not_found("Resource not found"))


def internal_error_handler(_e):
    return error_response(errors.invalid_request("Malformed request"))
