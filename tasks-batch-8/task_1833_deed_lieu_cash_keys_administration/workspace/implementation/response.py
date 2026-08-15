"""Response envelope helpers matching the scaffold's response_envelope spec."""
import random
import string

from flask import jsonify

from db import now_dt, iso_ts


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ts(now_dt()),
    }


def success(obj, http_status: int = 200, pagination: dict | None = None):
    """Build the standard success envelope.

    pagination: when not None, a dict with limit/offset/total_count/has_more
    which is merged into meta and response_type becomes "array".
    """
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
        body = {"meta": meta, "response_type": "array", "data": obj}
    else:
        body = {"meta": meta, "response_type": "object", "data": obj}
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_pagination(args):
    """Parse limit/offset from query args with scaffold defaults.

    Returns (limit, offset) or raises ApiError(ERR_INVALID_REQUEST).
    """
    from errors import err

    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Slice items per limit/offset; returns (page, pagination_meta)."""
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
