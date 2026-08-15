import secrets
from flask import jsonify
import logical_clock as clock


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def arr(data, status=200):
    """Array response without pagination (e.g. PUT allocation-targets)."""
    return jsonify({"meta": _meta(), "response_type": "array", "data": data}), status


def page(items, limit, offset, total):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + limit) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def err(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status
