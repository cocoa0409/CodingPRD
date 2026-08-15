"""Standard response envelope helpers."""
import secrets

from flask import jsonify, request

from db import now_iso
from errors import invalid_request


def _request_id():
    return "req_" + secrets.token_hex(8)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(page, pagination, code=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), code


def error_body(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def paginate(items):
    """Apply limit/offset pagination from query params. Returns (page, meta)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("Parameter 'limit' must be an integer")
        if limit < 1:
            raise invalid_request("Parameter 'limit' must be >= 1")
        if limit > 100:
            limit = 100  # capped at maximum 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("Parameter 'offset' must be an integer")
        if offset < 0:
            raise invalid_request("Parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def list_response(items):
    page, meta = paginate(items)
    return ok_list(page, meta)
