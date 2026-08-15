"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import re
import secrets

from flask import jsonify, request

from db import now_iso
from errors import ApiError

_INT_RE = re.compile(r"^-?\d+$")


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def respond_list(records, serializer):
    """Sort by created_at ascending (insertion order breaks ties), paginate."""
    limit, offset = parse_pagination()
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serializer(r) for r in page], "array", 200, pagination)
