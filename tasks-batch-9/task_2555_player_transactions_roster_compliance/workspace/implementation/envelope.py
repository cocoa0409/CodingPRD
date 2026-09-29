"""Standard response envelope (PRD section 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

from errors import fail
from store import db, fmt_ms, new_request_id

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ms(db.clock),
    }


def single(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty(status=200):
    return single({}, status)


def collection(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s below minimum" % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s above maximum" % name)
    return value


def page_params():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(records, serializer):
    """Apply the declared filters already handled by the caller, then page."""
    limit, offset = page_params()
    total = len(records)
    window = records[offset:offset + limit]
    return collection([serializer(item) for item in window], total, limit, offset)


def filter_records(records, spec):
    """spec maps query-parameter name -> record field name."""
    out = records
    for param, field in spec.items():
        wanted = request.args.get(param)
        if wanted is None or wanted == "":
            continue
        out = [item for item in out if item.get(field) == wanted]
    return out
