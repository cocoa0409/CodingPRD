"""Response envelope helpers (PRD section 2.2)."""

import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def iso_ms(value):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def serialize(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data if data is not None else {})}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": serialize(list(rows))}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
