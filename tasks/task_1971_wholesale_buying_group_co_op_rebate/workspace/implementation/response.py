"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import secrets
import string

from flask import jsonify, request

import db
from errors import ApiError, err_invalid_request

ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(ALPHABET) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (ties broken by creation order), then slice."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
