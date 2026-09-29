"""Response envelope helpers (PRD 2.2)."""
from flask import jsonify

from store import db, serialize
from util import fmt_ts, request_id


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data),
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in rows],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
