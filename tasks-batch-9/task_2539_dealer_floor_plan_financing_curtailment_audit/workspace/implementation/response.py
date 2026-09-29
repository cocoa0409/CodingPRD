"""Response envelope of PRD section 2.2 and the pagination contract of 2.3."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALNUM = string.ascii_letters + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": db.now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(items, limit, offset, total_count):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(items)) < total_count,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if str(value) != text and text.lstrip("+") != str(value):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above its maximum." % name)
    return value


def page_params():
    """limit / offset, rejected (never clamped) when out of range."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(records, serializer):
    limit, offset = page_params()
    total = len(records)
    window = records[offset:offset + limit]
    return collection([serializer(row) for row in window], limit, offset, total)


# --------------------------------------------------------------------------
# Query-string filters -- exact match, conjunctive.
# --------------------------------------------------------------------------


def filter_value(name, allowed=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if allowed is not None and raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s is outside its enumeration." % name)
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be true or false." % name)


def filter_instant(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return db.parse_instant(raw)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % name)


def apply_filters(records, spec):
    """spec: list of (field_name, expected_value); None values are ignored."""
    result = records
    for field, expected in spec:
        if expected is None:
            continue
        result = [row for row in result if row.get(field) == expected]
    return result
