"""Response envelope helpers (PRD §2.2, §2.3)."""

import secrets
from flask import jsonify

import db as _db


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": _db.now_iso(),
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    """Parse limit/offset query params. Defaults: limit=10 (min 1, max 100), offset=0."""
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            from errors import err_invalid_request
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            from errors import err_invalid_request
            raise err_invalid_request("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            from errors import err_invalid_request
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            from errors import err_invalid_request
            raise err_invalid_request("offset must be >= 0")
    return limit, offset
