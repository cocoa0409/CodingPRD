"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from errors import fail
from store import now_iso, serialize

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    if isinstance(data, dict):
        payload = serialize(data)
    else:
        payload = data if data is not None else {}
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {"meta": meta, "response_type": "array",
            "data": [serialize(row) for row in window]}
    return jsonify(body), 200


def error_response(error_id, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body)


def _int_param(name, default):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "Query parameter %s must be an integer." % name)
    value = int(text)
    return value


def pagination():
    """Read and validate `limit` and `offset` (PRD 2.3)."""
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def filter_value(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    return raw
