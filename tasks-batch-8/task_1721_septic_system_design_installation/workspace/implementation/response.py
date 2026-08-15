"""Standard response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2)."""

import uuid

from flask import jsonify, request

import db
import errors


def _rid():
    return "req_" + uuid.uuid4().hex[:20]


def _meta(**extra):
    meta = {
        "api_request_id": _rid(),
        "api_request_timestamp": db.now_iso(),
    }
    meta.update(extra)
    return meta


def respond_object(rec, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": db.public(rec),
    }
    return jsonify(body), status


def pagination_params():
    """Parse limit/offset per §1.0 defaults (limit 10, min 1, max 100; offset 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def respond_list(rows):
    """rows must already be filtered; sorting + pagination applied here."""
    limit, offset = pagination_params()
    ordered = db.sorted_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    body = {
        "meta": _meta(limit=limit, offset=offset, total_count=total, has_more=has_more),
        "response_type": "array",
        "data": [db.public(r) for r in page],
    }
    return jsonify(body), 200


def respond_error(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
