"""Response envelope helpers (PRD section 2.2) and pagination (section 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError, invalid
from store import clock, iso, serialize, serialize_many

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(clock()),
    }


def object_response(row, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": serialize(row) if row is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def array_response(rows, status=200):
    """A 2xx array payload that is not a paginated list endpoint."""
    body = {
        "meta": base_meta(),
        "response_type": "array",
        "data": serialize_many(rows),
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(rows) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": serialize_many(rows),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be at most %d." % (name, maximum))
    return value


def page_params():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginated(rows):
    """Apply limit/offset to an already ordered row list."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response(window, limit, offset, total)


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def float_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise invalid("%s must be a number." % name)
