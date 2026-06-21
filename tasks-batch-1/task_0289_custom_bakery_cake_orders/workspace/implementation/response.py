"""Standard response envelope helpers (PRD §2.2) and pagination (§2.3)."""
import random
import string

from flask import jsonify

import clock
from errors import err, ERR_VALIDATION_PAGINATION

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso_millis(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def parse_pagination(args):
    """Parse and validate limit/offset query params. Raises ApiError on bad bounds."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(ERR_VALIDATION_PAGINATION, "limit out of bounds")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer")
        if offset < PAGINATION_MIN_OFFSET:
            raise err(ERR_VALIDATION_PAGINATION, "offset out of bounds")

    return limit, offset


def paginate(items, limit, offset):
    """Slice items and return (page, pagination_meta). items must be pre-sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def list_response(items, limit, offset):
    page, pagination = paginate(items, limit, offset)
    return success(page, status=200, response_type="array", pagination=pagination)
