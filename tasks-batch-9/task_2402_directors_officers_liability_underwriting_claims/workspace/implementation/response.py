"""The standard response envelope (PRD 2.2)."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt_dt(clock.now()),
    }


def serialize_value(value):
    if isinstance(value, datetime):
        return clock.fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    return value


def serialize(record):
    """Project a stored record into its JSON representation."""
    return {
        key: serialize_value(value)
        for key, value in record.items()
        if not key.startswith("_")
    }


def object_response(record, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": serialize(record) if record is not None else {},
    }
    return jsonify(body), status


def raw_response(payload, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": serialize_value(payload),
    }
    return jsonify(body), status


def list_response(records, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(records) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(record) for record in records],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
