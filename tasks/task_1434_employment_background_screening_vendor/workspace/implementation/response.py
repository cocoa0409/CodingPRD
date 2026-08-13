"""Response envelope helpers (SCAFFOLD response_envelope; PRD section 2.2)."""
import secrets
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from timeutil import now, fmt


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt(now()),
    }


def serialize(value):
    """Recursively convert internal values to JSON-safe values."""
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if k != "_seq"}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return fmt(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data)}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array",
            "data": [serialize(i) for i in items]}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
