"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

from errors import fail
from util import fmt_dt, new_request_id, now_utc

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_utc()),
    }
    if extra:
        meta.update(extra)
    return meta


def public(entity):
    """Strip internal bookkeeping keys from a stored entity."""
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def entity_response(entity, status=200):
    return ok(public(entity), status)


def list_response(items, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(items)) < total,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": [public(i) for i in items]}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return value


def page_params():
    limit = _query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paged(items):
    """Apply the pagination window to an already-sorted, already-filtered list."""
    limit, offset = page_params()
    total = len(items)
    window = items[offset : offset + limit]
    return list_response(window, limit, offset, total)
