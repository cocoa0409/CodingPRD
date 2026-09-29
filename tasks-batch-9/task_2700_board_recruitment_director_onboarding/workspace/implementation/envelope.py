"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from store import wall_now

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": wall_now()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def page_params():
    """limit defaults to 10, clamped to [1, 100]; offset defaults to 0."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN:
        limit = PAGE_LIMIT_MIN
    if limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows):
    """Apply the pagination window and emit the list envelope."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list(window, limit, offset, total)
