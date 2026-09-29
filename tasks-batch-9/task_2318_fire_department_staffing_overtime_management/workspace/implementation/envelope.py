"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import db, serialize

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _envelope(response_type, data, status, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    response = jsonify(body)
    response.status_code = status
    return response


def ok_object(entity, status=200):
    db.commit()
    return _envelope("object", serialize(entity), status)


def created_object(entity):
    return ok_object(entity, 201)


def ok_raw(payload, status=200):
    db.commit()
    return _envelope("object", payload, status)


def error_response(error_id, message, status):
    db.discard()
    return _envelope("error", {"error_id": error_id, "message": message}, status)


def read_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def ok_list(items):
    limit, offset = read_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    db.commit()
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return _envelope("array", [serialize(e) for e in page], 200, meta_extra)
