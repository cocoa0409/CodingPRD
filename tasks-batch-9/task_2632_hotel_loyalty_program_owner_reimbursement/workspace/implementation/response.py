"""Response envelope helpers (PRD section 2.2 and 2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def object_response(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body), status


def created_response(payload):
    return object_response(payload, 201)


def empty_response(status=200):
    return object_response({}, status)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _page_int(name, raw, minimum, maximum):
    """A supplied pagination parameter must be a whole number inside the range the
    PRD declares for it; a value outside that range is not accepted and is not
    quietly substituted (PRD section 2.3 read with the request-shape step of the
    validation order in section 2.6)."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' is outside the accepted range." % name)
    return value


def page_params():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _page_int("limit", raw_limit, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _page_int("offset", raw_offset, 0, None)
    return limit, offset


def collection_response(records):
    """records: already filtered and ordered list of raw rows."""
    limit, offset = page_params()
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [db.public(r) for r in page],
    }
    return jsonify(body), 200
