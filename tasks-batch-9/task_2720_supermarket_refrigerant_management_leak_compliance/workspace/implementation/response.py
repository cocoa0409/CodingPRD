"""Standard response envelope (PRD 2.2) and offset pagination (PRD 2.3)."""
import datetime as _dt
from decimal import Decimal

from flask import jsonify, request

import db
import util
from errors import ApiError, invalid


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.fmt_instant(db.db.clock),
    }


def jsonable(value):
    """Convert stored values into their JSON representation.

    Instants render as ISO 8601 UTC with exactly three fractional digits;
    Decimals render as JSON numbers carrying their quantised scale.
    """
    if isinstance(value, _dt.datetime):
        return util.fmt_instant(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(entity):
    return jsonable(entity)


def ok(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(payload),
    }
    return jsonify(body), status


def created(payload):
    return ok(payload, 201)


def collection(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(item) for item in items],
    }
    return jsonify(body), 200


def error_body(error):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }


def read_pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be at least 0")
    return limit, offset


def sort_key(entity):
    """PRD 2.3: created_at ascending, insertion order as the tie-breaker."""
    return (entity["created_at"], entity["_seq"])


def listing(values, filters=None):
    """Apply conjunctive equality filters, order, paginate and envelope."""
    items = list(values)
    if filters:
        for field, wanted in filters.items():
            if wanted is None:
                continue
            items = [item for item in items if item.get(field) == wanted]
    items.sort(key=sort_key)
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return collection(page, limit, offset, total)


def bool_filter(name):
    """Parse a boolean query filter; returns None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("%s must be true or false" % name)
