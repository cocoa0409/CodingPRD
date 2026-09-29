"""Response envelope + pagination (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

import clock
from errors import fail

ALNUM = string.ascii_lowercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def created(data):
    return ok(data, 201)


def array_ok(rows, status=200):
    """Array payload that is not a paginated collection."""
    return jsonify({
        "meta": _meta(),
        "response_type": "array",
        "data": rows,
    }), status


def collection(rows, limit, offset, total_count):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(rows) < total_count,
        }),
        "response_type": "array",
        "data": rows,
    }), 200


def error_body(error_id, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def page_params():
    limit = _int_param("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _int_param("offset", 0, 0)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return collection([serializer(r) for r in window], limit, offset, total)
