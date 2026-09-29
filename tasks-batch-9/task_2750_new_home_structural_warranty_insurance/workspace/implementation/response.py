"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import err

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": db.wall_now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(raw):
    text = raw.strip()
    if text == "":
        raise err("ERR_INVALID_PAGINATION", "pagination parameter must be an integer")
    if text[0] in "+-":
        digits = text[1:]
    else:
        digits = text
    if not digits.isdigit():
        raise err("ERR_INVALID_PAGINATION", "pagination parameter must be an integer")
    return int(text)


def pagination():
    """Read and validate `limit` / `offset` (PRD 2.3)."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_param(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err("ERR_INVALID_PAGINATION", "limit must be between 1 and 100 inclusive")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_param(raw_offset)
        if offset < PAGE_OFFSET_MIN:
            raise err("ERR_INVALID_PAGINATION", "offset must be 0 or greater")
    return limit, offset


def paginate(rows, serializer=db.public):
    """Validate pagination, slice the (already sorted and filtered) rows and
    return the standard list envelope."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
