"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from util import fmt_dt

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(recs, args):
    """Sort by created_at ascending, apply filters already applied by caller."""
    limit, offset = parse_pagination(args)
    total = len(recs)
    page = recs[offset:offset + limit]
    return limit, offset, total, page
