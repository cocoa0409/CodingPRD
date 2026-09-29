"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string
from decimal import Decimal

from flask import jsonify, request

from datetimes import wall_now_iso
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def scrub(value):
    """Strip internal keys and turn Decimals into JSON numbers."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def object_response(data, http_status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": scrub(data),
    }
    return jsonify(body), http_status


def array_response(rows, limit, offset, total_count, http_status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [scrub(r) for r in rows],
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, PAGINATION_MIN_OFFSET, None)
    return limit, offset


def paginate(rows):
    """Apply the limit/offset window, returning (page, limit, offset, total)."""
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


def listing(rows):
    page, limit, offset, total = paginate(rows)
    return array_response(page, limit, offset, total)
