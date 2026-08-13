"""Response envelope (SCAFFOLD response_envelope / PRD 2.2) and pagination."""
import random
import string

from flask import request

from errors import ApiError
from util import wall_ts


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success(data, code=200, response_type="object", page_meta=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": wall_ts()}
    if page_meta is not None:
        meta.update(page_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return body, code


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": _request_id(),
                 "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items):
    """limit/offset per PRD 2.3: default 10, min 1, max 100, offset default 0.

    Returns (page_items, page_meta). Items are pre-sorted (created_at ASC).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
