"""Response envelope (PRD section 2.2)."""

import random
import string

from flask import jsonify, request

import clock
from errors import ApiError

_ALPHABET = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def single(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def collection(items, limit, offset, total_count, status=200):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    # PRD section 2.2: the error payload lives in `data`, and `meta` carries only
    # the request id and timestamp.
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def pagination():
    """Read and validate limit/offset (PRD section 2.2)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")

    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset : offset + limit], total
