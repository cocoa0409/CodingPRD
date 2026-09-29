"""Response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def serialize(row):
    """Project a stored row into its public representation."""
    if row is None:
        return {}
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data) if not isinstance(data, dict) else jsonable(data),
    }
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) if isinstance(r, dict) else jsonable(r) for r in items],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(collection, limit, offset):
    total = len(collection)
    return collection[offset:offset + limit], total
