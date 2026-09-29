"""Response envelope helpers (PRD §2.2, §2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    PAGE_OFFSET_MIN,
)
from errors import fail
from timeutil import iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_params():
    """Read and validate limit/offset from the query string (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT

    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )

    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < PAGE_OFFSET_MIN:
            fail("ERR_INVALID_REQUEST", "offset must be at least %d." % PAGE_OFFSET_MIN)

    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
