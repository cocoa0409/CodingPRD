"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import db, iso, public

ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.clock),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def row_response(row, status=200):
    return object_response(public(row), status)


def list_response(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in page],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ------------------------------------------------------------------ pagination

def _parse_int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    """Last rung of the refusal ladder: parse limit/offset."""
    limit = _parse_int_param(request.args.get("limit"))
    offset = _parse_int_param(request.args.get("offset"))
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset
