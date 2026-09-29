"""Standard success / error envelope (PRD 2.2) plus JSON serialisation of stored rows."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from util import fmt_dt, new_request_id


def serialize(value):
    """Recursively render a stored row for JSON: datetimes as ISO-8601 with 3 fractional
    digits, Decimals as plain numbers, internal underscore keys dropped."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            out[key] = serialize(item)
        return out
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if value == as_int else float(value)
    return value


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
