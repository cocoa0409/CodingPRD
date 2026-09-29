"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond // 1000,
    )


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'%s' may not be lower than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'%s' may not be higher than %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT,
                       PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginated(rows, serializer):
    """rows must already be in the endpoint's declared sort order."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
