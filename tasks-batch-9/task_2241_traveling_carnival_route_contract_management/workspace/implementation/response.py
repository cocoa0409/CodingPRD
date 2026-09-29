"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ERR_INVALID_REQUEST, ApiError

ALPHABET = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHABET) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_params():
    """PRD 2.3: limit defaults to 10, min 1, max 100; offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset may not be negative.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
