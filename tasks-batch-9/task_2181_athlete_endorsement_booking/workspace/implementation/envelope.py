"""Standard response envelope (PRD section 2.2) and pagination (2.3)."""

import datetime as _dt

from flask import jsonify, request

from errors import ApiError
from store import public, request_id, sorted_rows

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _wall_now():
    value = _dt.datetime.now(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _wall_now()}


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data) if isinstance(data, dict) else data}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def read_pagination():
    """limit / offset from the query string, validated per PRD 2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT

    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginated(rows, limit=None, offset=None, presort=True):
    if limit is None or offset is None:
        limit, offset = read_pagination()
    rows = sorted_rows(rows) if presort else list(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in page],
    }
    return jsonify(body), 200
