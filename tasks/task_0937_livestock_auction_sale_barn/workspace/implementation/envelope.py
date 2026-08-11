"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

import config
from clock import clock, render_instant

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_instant(clock.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def pagination():
    """limit defaults to 10, floor 1, ceiling 100; offset defaults to 0."""
    limit = _int_arg("limit", config.PAGINATION_DEFAULT_LIMIT)
    offset = _int_arg("offset", config.PAGINATION_DEFAULT_OFFSET)
    if limit < config.PAGINATION_MIN_LIMIT:
        limit = config.PAGINATION_MIN_LIMIT
    if limit > config.PAGINATION_MAX_LIMIT:
        limit = config.PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, serializer):
    """Sort by created_at ascending (insertion order), window, serialize."""
    limit, offset = pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)


def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
