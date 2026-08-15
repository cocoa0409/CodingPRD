"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import secrets
from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": db.now_iso(),
    }


def ok(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def list_response(items, limit, offset):
    """Items must already be filtered + sorted. Applies pagination envelope."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return ok([db.pub(e) for e in page], "array", 200, pagination)
