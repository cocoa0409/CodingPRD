"""The response envelope of PRD section 2.2 and the pagination contract of 2.3."""

from flask import jsonify, request

from errors import ApiError
from util import new_request_id, wall_now_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def ok(data, status=200):
    """A single-resource success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


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
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Invalid %s parameter" % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below its minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s exceeds its maximum" % name)
    return value


def pagination():
    """Read ``limit`` and ``offset`` per PRD section 2.3."""
    limit = _int_param(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginated(rows, serializer):
    """A list success envelope.  ``rows`` must already be filtered and ordered."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200
