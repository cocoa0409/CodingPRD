"""Response envelope helpers (PRD §2.2, scaffold §1.0).

Success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id": "...", "message": "..." } }
"""
from flask import jsonify

import db


def _meta(extra=None):
    m = {"api_request_id": db.request_id(), "api_request_timestamp": db.iso(db.now())}
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message=""):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), http_status
