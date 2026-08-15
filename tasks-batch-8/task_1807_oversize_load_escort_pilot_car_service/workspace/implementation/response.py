"""Standard response envelope helpers (scaffold response_envelope, verbatim shape)."""

import uuid

from flask import jsonify, g

import db
from util import fmt_dt


def _meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt(db.now()),
    }


def success_object(payload, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": payload,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, total_count, limit, offset, status=200):
    meta = _meta_base()
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


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def pagination_params(request):
    """Read limit/offset query params with defaults 10/0, clamped to [1,100] / [0,inf)."""
    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            from errors import ERR_INVALID_REQUEST, raise_err
            raise_err(ERR_INVALID_REQUEST, f"Query parameter {name} must be an integer")
    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(request, rows):
    """rows: full ordered list of serialized dicts. Returns a list response."""
    limit, offset = pagination_params(request)
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list(page, total, limit, offset)
