"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError
from store import now_iso

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def jsonable(value):
    """Recursively convert stored values into JSON-safe ones.

    Decimals become JSON numbers; private bookkeeping keys (leading underscore)
    are stripped.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict(
            (k, jsonable(v)) for k, v in value.items() if not k.startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(list(rows))}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------- #
# pagination + query filters
# --------------------------------------------------------------------------- #


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is above its maximum." % name)
    return value


def page_params():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, serializer=None):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    if serializer is not None:
        window = [serializer(r) for r in window]
    return ok_list(window, limit, offset, total)


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = str(raw).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)
