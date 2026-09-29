"""Response envelope construction (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import store
from util import iso

ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(store.clock),
    }


def object_response(data, status=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), status


def empty_response(status=200):
    return object_response({}, status)


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_query(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s may not be below %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s may not exceed %d." % (name, maximum))
    return value


def pagination_params():
    """Resolve limit/offset, rejecting out-of-bound values with ERR_INVALID_REQUEST."""
    limit = _int_query("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_query("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200
