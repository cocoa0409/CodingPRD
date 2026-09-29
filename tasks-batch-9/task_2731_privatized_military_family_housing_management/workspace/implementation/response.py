"""Response envelope helpers (PRD 2.2 / 2.3)."""

from datetime import datetime, timezone

from flask import jsonify

from db import iso, public, request_id


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else (data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty(status=200):
    return ok({}, status)


def page(rows, limit, offset, status=200):
    """rows: already-filtered, already-ordered list of raw rows."""
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
