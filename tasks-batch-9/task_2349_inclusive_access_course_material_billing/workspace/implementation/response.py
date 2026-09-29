"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

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


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def envelope(data, response_type, meta_extra=None):
    return {"meta": _meta(meta_extra), "response_type": response_type, "data": data}


def object_response(data, status=200):
    return jsonify(envelope(data, "object")), status


def array_response(items, meta_extra=None, status=200):
    return jsonify(envelope(items, "array", meta_extra)), status


def error_response(error_id, message, status):
    body = envelope({"error_id": error_id, "message": message}, "error")
    return jsonify(body), status


def _int_arg(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s is below its minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s is above its maximum" % name)
    return value


def paginate(items, serializer):
    limit = _int_arg("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_arg("offset", PAGE_OFFSET_DEFAULT, 0, None)
    total = len(items)
    page = items[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return array_response([serializer(x) for x in page], meta_extra)


def apply_filters(items, filters):
    """filters: list of (query_param_name, record_field_name)."""
    out = items
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        out = [r for r in out if _as_str(r.get(field)) == raw]
    return out


def _as_str(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
