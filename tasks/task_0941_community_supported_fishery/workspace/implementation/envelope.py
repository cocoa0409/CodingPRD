"""The response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify

import clock
import ids
import store

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": ids.new_request_id(),
        "api_request_timestamp": clock.render_instant(clock.now()),
    }


def object_response(data, status=200):
    store.commit()
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def raw_object_response(data, status=200):
    """An object response whose data payload is already a plain dict."""
    return object_response(data, status)


def list_response(rows, limit, offset, total):
    store.commit()
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_params(args):
    """limit/offset per PRD 2.3.

    PRD 2.3 states the bounds ("may not be smaller than 1, and may not be
    larger than 100") but declares no rejection for a value outside them, and
    the ERR_VALIDATION rung (rung 6) is explicitly scoped to write endpoints,
    so out-of-range paging values are clamped rather than rejected.
    """
    limit = _as_int(args.get("limit"), PAGE_LIMIT_DEFAULT)
    offset = _as_int(args.get("offset"), PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN:
        limit = PAGE_LIMIT_MIN
    if limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def _as_int(value, fallback):
    if value is None or value == "":
        return fallback
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def paginate(rows, serializer, args):
    limit, offset = page_params(args)
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
