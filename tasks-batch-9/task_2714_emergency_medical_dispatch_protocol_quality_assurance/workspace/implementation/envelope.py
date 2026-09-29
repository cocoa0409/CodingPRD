"""Standard response envelope (PRD 2.2) and JSON-safe conversion."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        instant.year,
        instant.month,
        instant.day,
        instant.hour,
        instant.minute,
        instant.second,
        instant.microsecond // 1000,
    )


def jsonable(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict(
            (k, jsonable(v)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(row):
    """Serialize a stored row, dropping internal bookkeeping keys."""
    return jsonable(row)


def _meta():
    wall = datetime.now(timezone.utc)
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(wall)}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data)}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(items)}
    return jsonify(body), status


def ok_array(items, status=200):
    """A 2xx array payload that is not a paginated list surface."""
    body = {"meta": _meta(), "response_type": "array", "data": jsonable(items)}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset: offset + limit]
    return window, total
