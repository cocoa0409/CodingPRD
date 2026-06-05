"""Standard response envelope (PRD §2.2 / SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id", "api_request_timestamp", [pagination...] },
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error", "data": { "error_id", "message" } }
"""
from flask import jsonify

from util import iso, new_request_id
import clock


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    """List response with the four pagination fields in meta (PRD §2.3)."""
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), status


def array_plain(items, status=200):
    """List response WITHOUT pagination fields in meta — for the list endpoints
    PRD §2.3 does not name (criteria, arms, consent-documents, irb-reviews,
    visits, adverse-events, payments)."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
