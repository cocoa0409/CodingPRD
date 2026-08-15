"""Standard response envelope helpers per SCAFFOLD response_envelope and PRD section 2.2."""

import random
import string
from flask import jsonify
from db import store, iso_format


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _meta(include_pagination=False, limit=None, offset=None, total_count=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_format(store.now()),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = (offset + limit) < total_count if (limit is not None and total_count is not None) else False
    return m


def success_object(data, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count, status_code=200):
    body = {
        "meta": _meta(include_pagination=True, limit=limit, offset=offset, total_count=total_count),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
