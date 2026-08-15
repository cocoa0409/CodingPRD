"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2, §2.3)."""

import secrets

from flask import jsonify, request

from db import now_str
from errors import ApiError


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": now_str(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0 (SCAFFOLD §1.0)."""
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(all_records, serializer):
    """Sort by created_at ascending (insertion-order tie-break), paginate, wrap.
    (PRD §2.3: lists sorted by creation timestamp ascending.)"""
    limit, offset = parse_pagination()
    records = sorted(all_records, key=lambda r: r["_seq"])
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
