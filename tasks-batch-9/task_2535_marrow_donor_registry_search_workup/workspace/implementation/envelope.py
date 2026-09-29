"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import request

from errors import ApiError
from store import db, fmt_instant

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(db.now()),
    }


def success(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return body, status


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginated(rows, limit, offset):
    """Slice already-ordered rows and build the list envelope."""
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return {"meta": meta, "response_type": "array", "data": page}, 200


def read_pagination():
    """PRD 2.3.  limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _int_param(raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _int_param(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def _int_param(raw):
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(text)
    return value
