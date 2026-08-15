"""Standard response envelope helpers (PRD §2.2, §2.3).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more to meta.
"""
import uuid

from flask import jsonify

from clock import now_iso


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_params(args):
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset
