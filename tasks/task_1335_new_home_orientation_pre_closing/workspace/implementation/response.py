"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success: { "meta": { api_request_id, api_request_timestamp, [pagination] },
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import uuid
from datetime import datetime, timezone

from flask import jsonify

from errors import err_validation


def _meta(pagination=None):
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": ts,
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit/offset per scaffold: limit default 10 (min 1, max 100), offset 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'limit' must be an integer.")
        if isinstance(limit, bool):
            raise err_validation("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise err_validation("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("Query parameter 'offset' must be an integer.")
        if isinstance(offset, bool):
            raise err_validation("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise err_validation("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(sorted_items, args):
    """Apply limit/offset, returning (page, pagination-meta dict)."""
    limit, offset = parse_pagination(args)
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination
