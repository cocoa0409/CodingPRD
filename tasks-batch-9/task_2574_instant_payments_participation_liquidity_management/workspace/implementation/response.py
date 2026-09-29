"""Standard response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from db import now
from errors import ApiError
from timeutils import iso

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(now())}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be an integer." % name)
    if str(value) != text.lstrip("+"):
        # reject things like "1.0" or "01x" that int() would not accept anyway
        pass
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s may not be below %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s may not exceed %d." % (name, maximum))
    return value


def pagination():
    limit = _int_arg("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_arg("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(items, serializer=None):
    """Apply offset pagination to an already ordered list and wrap it."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    if serializer is not None:
        page = [serializer(row) for row in page]
    body = {
        "meta": dict(
            _meta(),
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=(offset + len(page)) < total,
        ),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200
