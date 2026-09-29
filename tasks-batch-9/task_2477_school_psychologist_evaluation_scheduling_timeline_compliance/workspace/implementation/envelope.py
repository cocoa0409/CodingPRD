"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string

from flask import jsonify

from errors import ApiError
from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(args, name, default, minimum, maximum):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination(args):
    limit = _int_param(args, "limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param(args, "offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
