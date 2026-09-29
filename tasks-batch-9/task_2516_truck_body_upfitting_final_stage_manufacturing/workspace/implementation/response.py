"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.wall_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def array_response(rows, limit, offset, total_count, status=200):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


def _parse_int_param(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def read_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0).
    Anything outside those bounds is ERR_INVALID_REQUEST (422)."""
    limit = _parse_int_param(request.args.get("limit"), "limit")
    offset = _parse_int_param(request.args.get("offset"), "offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
        )
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be greater than or equal to 0.")
    return limit, offset


def paginate(rows):
    """Sort by created_at ascending, slice the window, and emit the envelope."""
    limit, offset = read_pagination()
    ordered = sorted(rows, key=db.sort_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return array_response([db.serialize(r) for r in window], limit, offset, total)
