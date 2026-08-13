"""Standard response envelope (PRD §2.2)."""
import uuid

from flask import jsonify, request

from db import now_iso


def _request_id():
    return "req_" + uuid.uuid4().hex


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = api_error.http_status
    return resp


def get_body():
    """Return the JSON request body as a dict; {} when absent. Non-dict JSON is invalid."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data
