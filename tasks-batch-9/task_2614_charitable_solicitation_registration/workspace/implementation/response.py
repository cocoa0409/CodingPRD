"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond // 1000,
    )


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """A single-resource (or computed-object) success envelope."""
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count, status=200):
    """A list success envelope carrying the pagination fields in ``meta``."""
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }),
        "response_type": "array",
        "data": rows,
    }), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_params():
    """Read and validate ``limit`` and ``offset`` from the query string."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d inclusive." % (LIMIT_MIN, LIMIT_MAX),
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(rows):
    """Apply pagination to an already-sorted, already-filtered row list."""
    limit, offset = pagination_params()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


def query_int(name):
    """Read an optional integer query filter; unparseable values match nothing."""
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return _NO_MATCH


class _NoMatch(object):
    def __eq__(self, other):
        return False

    def __hash__(self):
        return id(self)


_NO_MATCH = _NoMatch()
