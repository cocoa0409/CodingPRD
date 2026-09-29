"""Standard response envelope (PRD section 2.2)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from util import format_dt

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": format_dt(now),
    }


def convert(value):
    if isinstance(value, datetime):
        return format_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: convert(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [convert(v) for v in value]
    return value


def serialize(record):
    """Public representation of a stored row: every non-internal field."""
    if record is None:
        return None
    return {k: convert(v) for k, v in record.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": convert(data) if not isinstance(data, dict) else convert(data),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [convert(row) for row in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
