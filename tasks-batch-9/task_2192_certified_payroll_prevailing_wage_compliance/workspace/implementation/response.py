"""Standard response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    stamp = datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (stamp.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


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


def paginated(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must not exceed %d." % (name, maximum))
    return value


def pagination():
    """Read and validate limit/offset query parameters."""
    limit = _int_param("limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _int_param("offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN, None)
    return limit, offset
