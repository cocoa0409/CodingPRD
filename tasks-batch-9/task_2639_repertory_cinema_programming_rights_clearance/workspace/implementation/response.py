"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from timeutil import fmt_instant

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _int_param("offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN, None)
    return limit, offset


def paged(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
