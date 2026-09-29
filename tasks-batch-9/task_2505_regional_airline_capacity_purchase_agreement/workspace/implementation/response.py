"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify

from core import clock
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _parse_int_param(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination(args):
    """Read and validate limit/offset from the query string."""
    limit = _parse_int_param(args.get("limit"), "limit")
    offset = _parse_int_param(args.get("offset"), "offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        fail("ERR_INVALID_REQUEST",
             "limit must be between %d and %d inclusive"
             % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be at least 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def listing(rows, serializer, args):
    limit, offset = pagination(args)
    window, total = paginate(rows, limit, offset)
    return array_response([serializer(row) for row in window], limit, offset, total)
