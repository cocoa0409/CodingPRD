"""Response envelope helpers (PRD 2.2 / 2.3)."""
from flask import jsonify, request

import db
from errors import ApiError
from util import fmt_ts, new_request_id

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def envelope(data, response_type="object", pagination=None, status=200):
    db.commit()
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok(data):
    return envelope(data, "object", status=200)


def created(data):
    return envelope(data, "object", status=201)


def error_response(err):
    db.rollback()
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def read_pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_RANGE", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_RANGE", "offset may not be negative.")
    return limit, offset


def collection(rows, serializer):
    """Sort by created_at ASC, apply offset/limit, and build the array envelope."""
    limit, offset = read_pagination()
    rows = db.ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return envelope([serializer(r) for r in page], "array", pagination=pagination)
