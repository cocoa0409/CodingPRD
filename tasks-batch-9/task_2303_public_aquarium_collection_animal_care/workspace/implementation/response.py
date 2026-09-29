"""Response envelope helpers (SCAFFOLD.yaml section 1.0 / PRD section 2.2)."""

import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import db

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (value.microsecond // 1000)) + "Z"


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso(db.db.clock),
    }


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _plain(data),
    }
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": _plain(list(items)),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
