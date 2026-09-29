"""Response envelope helpers (meta / response_type / data)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import db, iso

ALNUM = string.ascii_uppercase + string.digits
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(db.clock),
    }


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s may not be larger than %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN,
                       PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(records, serializer):
    """Apply the declared default collation, window and envelope to a list."""
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: (r.get("created_at") or "",
                                             r.get("_seq") or 0))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
