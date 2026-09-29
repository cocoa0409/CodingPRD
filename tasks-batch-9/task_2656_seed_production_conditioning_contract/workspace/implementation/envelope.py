"""Response envelope helpers (PRD 2.2, SCAFFOLD response_envelope)."""

import datetime
import random
import string
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_ms(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(datetime.datetime.now(datetime.timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(list(items))}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
