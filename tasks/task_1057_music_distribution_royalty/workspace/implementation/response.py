"""Response envelope helpers — PRD §2.2 / §2.3."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def _clean(value):
    from db import format_iso

    if isinstance(value, datetime):
        return format_iso(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def serialize(row):
    return _clean(row)


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def read_pagination(args):
    """Parse and validate limit/offset — PRD §2.3."""
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def sort_key(row):
    return (row.get("created_at"), row.get("_seq", 0))


def paginate(rows, limit, offset):
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    return ordered[offset:offset + limit], total
