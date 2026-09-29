"""Standard response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import now_str, public, sort_rows

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_str()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def entity(row, status=200):
    return ok(public(row), status)


def entity_created(row):
    return ok(public(row), 201)


def empty(status=200):
    return ok({}, status)


def read_pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (min 0)."""
    limit = _int_param("limit", PAGINATION_LIMIT_DEFAULT)
    offset = _int_param("offset", PAGINATION_OFFSET_DEFAULT)
    if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < PAGINATION_OFFSET_MIN:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be 0 or greater.")
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(digits)
    return -value if negative else value


def collection(rows):
    """Filter-then-paginate a list of rows into the array envelope."""
    limit, offset = read_pagination()
    rows = sort_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {"meta": meta, "response_type": "array", "data": [public(r) for r in page]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
