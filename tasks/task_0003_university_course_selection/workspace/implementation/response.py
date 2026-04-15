"""Standard response envelope helpers.

The test harness expects:
  Success: { meta: { api_request_id, api_request_timestamp }, response_type: "object"|"array", data: ... }
  Error:   { meta: { api_request_id, api_request_timestamp }, response_type: "error", data: { error_id, message } }
  Paginated: { meta: { api_request_id, api_request_timestamp, total_count, has_more, limit, offset }, response_type: "array", data: [...] }
"""
import uuid
from flask import jsonify
from db import now_iso


def _request_id():
    return "csel_" + uuid.uuid4().hex[:10]


def _meta(**extra):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    m.update(extra)
    return m


def success_single(data, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, page_size, offset, total_results, next_page_token):
    """Return a paginated list response.

    The test harness validates: meta.total_count (int), meta.has_more (bool),
    meta.limit (int >0), meta.offset (int >=0).

    ``offset`` must be an integer (the numeric offset, not the opaque token).
    """
    has_more = next_page_token is not None

    body = {
        "meta": _meta(
            total_count=total_results,
            total_results=total_results,
            has_more=has_more,
            limit=page_size,
            page_size=page_size,
            offset=offset,
            next_page_token=next_page_token,
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, detail, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": detail,
        },
    }
    return jsonify(body), http_status
