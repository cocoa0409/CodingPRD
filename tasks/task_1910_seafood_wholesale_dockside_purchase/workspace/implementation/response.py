"""Response envelope helpers per PRD section 2.2.

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import uuid
from datetime import datetime, date
from decimal import Decimal

from flask import jsonify

from db import store
from util import fmt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt(store.clock),
    }


def _encode(value):
    if isinstance(value, datetime):
        return fmt(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def ok(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": _encode(data)}
    return jsonify(payload), status


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    payload = {"meta": meta, "response_type": "array", "data": _encode(items)}
    return jsonify(payload), 200


def err(error_id, status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
