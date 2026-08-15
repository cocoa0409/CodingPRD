"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string
from datetime import date, datetime

from flask import jsonify, request

from db import now_iso
from errors import ApiError, ERR_VALIDATION


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    """Success envelope. response_type 'array' iff this is a list response."""
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def err_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, serialize):
    """Apply pagination; returns (flask response, 200) with meta pagination."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok([serialize(x) for x in page], status=200, pagination=pagination)


def pub(rec):
    """Public serialization: drop internal '_' keys, dates -> YYYY-MM-DD."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
