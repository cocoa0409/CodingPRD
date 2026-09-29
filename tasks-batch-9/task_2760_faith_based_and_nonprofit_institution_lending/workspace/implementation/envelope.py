"""Response envelope helpers (PRD section 2.2) and pagination (section 2.3)."""

from flask import jsonify, request

import store
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.wall_now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' is out of range." % name)
    return value


def page_params():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def listing(rows, serializer):
    """Apply offset pagination to an already-filtered, already-sorted list."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200


def filter_rows(rows, spec):
    """spec: {field_name: query_param_name}; conjunctive equality filters."""
    out = rows
    for field, param in spec.items():
        value = request.args.get(param)
        if value is None or value == "":
            continue
        out = [r for r in out if r.get(field) == value]
    return out


def sort_created_desc(rows):
    return sorted(rows, key=lambda r: r["_seq"], reverse=True)


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: r["_seq"])
