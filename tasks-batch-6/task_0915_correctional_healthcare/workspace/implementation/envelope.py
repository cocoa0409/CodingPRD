"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": window}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def page_params(args):
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0).

    Anything outside those ranges is a payload-range failure -> ERR_VALIDATION.
    """
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100 inclusive")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
