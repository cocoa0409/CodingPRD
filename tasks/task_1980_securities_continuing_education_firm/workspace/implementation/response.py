"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST
from util import fmt_dt

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    # Request metadata uses the host wall clock; entity timestamps use the
    # logical clock (PRD 2.4 scopes the logical clock to derived timestamps).
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, status=200, is_list=False, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _parse_int_param(raw, name):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Query parameter '%s' must be an integer" % name)
    return value


def paginate(items):
    """Apply limit/offset per PRD 2.3 and return (page, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Query parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
