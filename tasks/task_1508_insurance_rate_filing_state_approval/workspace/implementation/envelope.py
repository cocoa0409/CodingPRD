"""Response envelope helpers (PRD §2.2 / scaffold response_envelope).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import uuid
from decimal import Decimal
from datetime import date, datetime

from flask import jsonify

from store import db
from timeutil import fmt_ts


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.clock),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def to_jsonable(value):
    """Convert internal representations to JSON-native values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize(entity, fields):
    """Project an entity dict to its public wire form (exact field set)."""
    return {name: to_jsonable(entity.get(name)) for name in fields}


def success(data, response_type="object", code=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


def list_response(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, response_type="array", code=200, pagination=pagination)


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
