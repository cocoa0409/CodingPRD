"""Response envelopes and pagination (PRD 2.2, 2.3)."""

from flask import jsonify, request

import store
from errors import ApiError

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.request_timestamp(),
    }


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listed(rows, limit, offset):
    """`rows` is the full filtered collection; slicing happens here."""
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": store.public_list(page)}
    return jsonify(body), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination():
    """Parse and validate ?limit=&offset= (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be an integer within [1, 100].")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "offset must be an integer >= 0.")
    return limit, offset


def _as_int(text):
    text = text.strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value
