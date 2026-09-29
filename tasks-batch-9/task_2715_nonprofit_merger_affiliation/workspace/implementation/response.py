"""Response envelope helpers — PRD section 2.2 / 2.3."""

from flask import jsonify

from clock import CLOCK
from db import new_request_id, serialize


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.now_iso(),
    }


def ok(data, status=200):
    """Single-resource (or computed-object) success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    """Apply offset/limit and return (page, total_count)."""
    total = len(rows)
    return rows[offset : offset + limit], total


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
