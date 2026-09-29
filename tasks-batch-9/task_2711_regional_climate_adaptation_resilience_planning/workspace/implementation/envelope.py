"""Standard response envelope and pagination (PRD 2.2 and 2.3)."""

from flask import jsonify, request

from core import clock, iso, new_request_id
from errors import fail

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(clock.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status


def page_params():
    """limit defaults to 10 in [1, 100]; offset defaults to 0 and is non-negative."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = LIMIT_DEFAULT
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    offset = OFFSET_DEFAULT
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")

    return limit, offset


def listing(rows, serializer):
    """Paginate an already-filtered, already-sorted row list."""
    limit, offset = page_params()
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
        "data": [serializer(row) for row in window],
    }
    return jsonify(body), 200


# ---------------------------------------------------------------------------
# Query-string filter helpers
# ---------------------------------------------------------------------------

def str_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def bool_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def int_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def match(rows, **filters):
    """Keep rows whose fields equal every supplied (non-None) filter value."""
    out = rows
    for field, wanted in filters.items():
        if wanted is None:
            continue
        out = [row for row in out if row.get(field) == wanted]
    return out
