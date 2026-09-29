"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

import db
from errors import ApiError
from util import iso

ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def api_request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """A single-resource (or empty) 2xx envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, page_meta, status=200):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if str(value) != text and text.lstrip("+") != str(value):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def pagination_params():
    limit = _int_param("limit", PAGINATION_LIMIT_DEFAULT,
                       PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _int_param("offset", PAGINATION_OFFSET_DEFAULT,
                        PAGINATION_OFFSET_MIN, None)
    return limit, offset


def paginate(rows):
    """Apply the page window and build the list meta block."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
