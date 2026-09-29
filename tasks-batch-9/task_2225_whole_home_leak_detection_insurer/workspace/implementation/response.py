"""Standard success / error envelopes (PRD section 2.2) and pagination."""
import random
import string

from flask import jsonify, request

import clock
from config import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import ApiError
from util import fmt_dt

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def page_params():
    """Read and validate limit / offset from the query string."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Query parameter 'limit' must be between %d and %d."
                % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def listing(items, serializer, limit=None, offset=None):
    """Build an array envelope with pagination metadata."""
    if limit is None or offset is None:
        limit, offset = page_params()
    total = len(items)
    window = items[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in window],
    }
    return jsonify(body), 200


def enum_filter(name, allowed):
    """Read an optional enum query filter; an unknown value is a 400."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def str_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)
