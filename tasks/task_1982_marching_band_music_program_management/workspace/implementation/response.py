"""Standard response envelope helpers."""
import random
import string
from flask import jsonify
from db import now_iso


def _gen_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + suffix


def success(data, status=200, is_list=False, pagination=None):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset with defaults; invalid -> ERR_INVALID_REQUEST."""
    from errors import raise_err, ERR_INVALID_REQUEST

    limit_s = args.get("limit", None)
    offset_s = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
