"""Response envelope helpers (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import iso, ordered, serialize

_ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20)),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % name)
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def _matches(value, raw):
    if value is None:
        return False
    if isinstance(value, bool):
        return raw.strip().lower() in (("true", "1") if value else ("false", "0"))
    return str(value) == raw


def apply_filters(rows, fields):
    """Apply exact-match query-string filters for the named row fields."""
    out = list(rows)
    for field in fields:
        raw = request.args.get(field)
        if raw is None or raw == "":
            continue
        out = [row for row in out if _matches(row.get(field), raw)]
    return out


def listing(rows, serializer=serialize):
    """Sort by created_at ascending, apply the window, build the envelope."""
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in window],
    }
    return jsonify(body), 200
