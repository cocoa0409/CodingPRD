"""Response envelope helpers (PRD 2.2)."""
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import clock
import constants

_ALNUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize_value(value):
    if isinstance(value, datetime):
        return clock.iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    if isinstance(value, tuple):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items() if not k.startswith("_")}
    return value


def serialize(record):
    return {k: serialize_value(v) for k, v in record.items() if not k.startswith("_")}


def object_response(record, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(record) if isinstance(record, dict) else serialize_value(record),
    }
    return jsonify(body), status


def list_response(records, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [serialize(r) for r in records],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


__all__ = [
    "object_response",
    "list_response",
    "error_response",
    "paginate",
    "serialize",
    "constants",
]
