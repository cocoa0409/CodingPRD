"""Response envelope helpers (PRD 2.2 / 2.3)."""
from flask import jsonify, request

from db import fmt_dt, now, request_id
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def list_response(rows, limit, offset):
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
        "data": window,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not re_int(text):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must be at most %d" % (name, maximum))
    return value


def re_int(text):
    if text.startswith("-"):
        return text[1:].isdigit()
    return text.isdigit()


def pagination():
    """Parse and validate limit/offset. Structural, so it runs first."""
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset
