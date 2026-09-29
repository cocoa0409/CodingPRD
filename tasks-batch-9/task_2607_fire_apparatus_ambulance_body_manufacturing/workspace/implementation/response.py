"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from db import by_created_at
from timeutil import now_iso

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": api_request_id(), "api_request_timestamp": now_iso()}


def jsonable(value):
    """Strip internal keys and render Decimals as JSON numbers."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        as_int = int(value)
        if value == as_int:
            return float(as_int)
        return float(value)
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, serializer=None):
    """Paginated list envelope. Rows arrive already filtered; sorting is here."""
    ordered = by_created_at(rows)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    payload = [serializer(r) if serializer else r for r in window]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {"meta": meta, "response_type": "array", "data": jsonable(payload)}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
