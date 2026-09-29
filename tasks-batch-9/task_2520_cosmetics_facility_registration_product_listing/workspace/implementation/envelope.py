"""Response envelope (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string

from flask import jsonify, request

import store
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_FIELDS = ("limit", "offset", "total_count", "has_more")
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso_ms(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, page):
    meta = _meta()
    meta["limit"] = page["limit"]
    meta["offset"] = page["offset"]
    meta["total_count"] = page["total_count"]
    meta["has_more"] = page["has_more"]
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def read_pagination():
    """PRD §2.3 — limit/offset with bounds; out-of-range is ERR_INVALID_REQUEST."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(records, serializer):
    limit, offset = read_pagination()
    total = len(records)
    window = records[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return ok_list([serializer(r) for r in window], page)
