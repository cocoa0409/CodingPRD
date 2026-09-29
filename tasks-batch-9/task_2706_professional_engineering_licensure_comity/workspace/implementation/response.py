"""Response envelope helpers (PRD 2.2 / 2.3)."""
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from util import fmt_iso, new_request_id, real_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(real_now()),
    }


def ser_val(value):
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, Decimal):
        as_float = float(value)
        return as_float
    if isinstance(value, list):
        return [ser_val(v) for v in value]
    if isinstance(value, dict):
        return {k: ser_val(v) for k, v in value.items()}
    return value


def serialize(row, fields):
    return {name: ser_val(row.get(name)) for name in fields}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": ser_val(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [ser_val(r) for r in rows]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error(error_id, message, status):
    return jsonify(error_body(error_id, message)), status
