"""Response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string
from datetime import timezone

from flask import jsonify, request

import constants as C
from db import db, fmt_ts
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now.astimezone(timezone.utc)),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def read_pagination():
    """Parse and validate limit/offset from the query string."""
    args = request.args
    limit = C.PAGINATION_DEFAULT_LIMIT
    offset = C.PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw)
        if limit is None or limit < C.PAGINATION_MIN_LIMIT or limit > C.PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", message="limit must be an integer from 1 to 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", message="offset must be an integer of at least 0.")
    return limit, offset


def _as_int(raw):
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
