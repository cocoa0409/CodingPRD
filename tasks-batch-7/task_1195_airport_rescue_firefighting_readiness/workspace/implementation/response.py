"""Standard response envelope helpers and pagination."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import serialize
from errors import ApiError, ERR_VALIDATION_FAILED


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _wall_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_ts(),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error(error_id, message, http_status):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_ts(),
    }
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION_FAILED, 400, "limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginated(items):
    """Sort by created_at ascending (creation sequence tie-break), slice, envelope."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    limit, offset = parse_pagination()
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serialize(e) for e in page], "array", 200, pagination=meta)
