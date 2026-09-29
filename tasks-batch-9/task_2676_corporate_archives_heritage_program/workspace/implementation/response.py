"""Response envelope helpers (PRD 2.2 / 2.3)."""

from flask import jsonify, request

from core import clock, fmt_instant, new_request_id, serialize
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_instant(clock.now()),
    }


def object_response(row, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": serialize(row) if row is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _positive_int(raw, name):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    return value


def pagination_params():
    limit = _positive_int(request.args.get("limit"), "limit")
    offset = _positive_int(request.args.get("offset"), "offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter 'limit' must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
        )
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def collection_response(rows):
    """Paginate an already filtered + sorted list of rows."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in page],
    }
    return jsonify(body), 200


def apply_filters(rows, spec):
    """spec: mapping of query-param name -> row field name."""
    out = rows
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [row for row in out if row.get(field) == raw]
    return out
