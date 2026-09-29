"""Response envelope helpers (PRD 2.2 / 2.3)."""
from flask import jsonify, request

from db import new_request_id, real_now_iso, serialize
from errors import bad_request

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": real_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data=None):
    return ok(data, 201)


def entity(row, status=200):
    return ok(serialize(row), status)


def entity_created(row):
    return ok(serialize(row), 201)


def listing(rows, limit, offset, total_count, serializer=serialize):
    page = [serializer(r) for r in rows]
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(page) < total_count,
            }
        ),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination():
    """Read and validate limit/offset from the query string."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT

    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise bad_request("limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer.")
        if offset < OFFSET_MIN:
            raise bad_request("offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset, serializer=serialize):
    total = len(rows)
    return listing(rows[offset : offset + limit], limit, offset, total, serializer)
