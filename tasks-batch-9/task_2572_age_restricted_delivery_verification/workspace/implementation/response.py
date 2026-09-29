"""Response envelope helpers -- exactly the shape declared in PRD section 2.2.

    success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
    error:   {"meta": {...}, "response_type": "error",
              "data": {"error_id": ..., "message": ...}}
"""
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from db import now_str
from errors import ApiError
from util import INT_RE, fmt_dt, new_request_id


def jsonable(value):
    """Decimal -> JSON number, date/datetime -> ISO strings. Never binary floats
    inside the arithmetic; the conversion happens only at the serialisation edge."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value

# PRD 2.3 pagination defaults
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def public(row):
    """Strip internal bookkeeping keys from a stored row."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_empty():
    return ok({}, 200)


def ok_list(rows, limit, offset, total_count):
    """List envelope: pagination fields live inside `meta` (PRD 2.2/2.3)."""
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": jsonable(rows)}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if not INT_RE.match(text):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must not exceed %d" % (name, maximum))
    return value


def pagination():
    """Returns (limit, offset), raising ERR_VALIDATION outside the declared bounds."""
    limit = _int_arg("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_arg("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(rows, limit, offset):
    """Slice an already-ordered, already-filtered row list."""
    total = len(rows)
    window = rows[offset:offset + limit]
    return [public(r) for r in window], total


def listing(rows, limit=None, offset=None):
    if limit is None or offset is None:
        limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)
