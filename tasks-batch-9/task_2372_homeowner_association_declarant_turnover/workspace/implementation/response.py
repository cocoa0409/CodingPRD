"""Standard response envelope (PRD §2.2, SCAFFOLD §1.0)."""
import random
import string

from flask import jsonify, request

import constants
import util
from errors import ApiError

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": util.real_now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def array_response(items, pagination, status=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def paginate(records):
    """Apply limit/offset and build the pagination fields for `meta`."""
    limit = _int_param(
        "limit",
        constants.PAGINATION_DEFAULT_LIMIT,
        constants.PAGINATION_MIN_LIMIT,
        constants.PAGINATION_MAX_LIMIT,
    )
    offset = _int_param("offset", constants.PAGINATION_DEFAULT_OFFSET, 0, None)
    total = len(records)
    window = records[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, pagination
