"""Response envelope of PRD 2.2 and pagination of PRD 2.3."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import db
from timeutil import render_instant

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_instant(db.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    from errors import ERROR_HTTP

    return jsonify(body), ERROR_HTTP[error_id]


def _parse_int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "pagination parameter must be an integer")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "pagination parameter must be an integer")
    value = int(text)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 with no upper bound."""
    limit = _parse_int_param(request.args.get("limit"))
    offset = _parse_int_param(request.args.get("offset"))
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < PAGE_OFFSET_MIN:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0")
    return limit, offset


def sort_key(row):
    """Default list ordering: created_at ascending, ties broken by id ascending
    in lexicographic byte order (PRD 2.3)."""
    return (row["created_at"], row["id"])


def paginate(rows, serializer):
    limit, offset = pagination()
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return list_response([serializer(r) for r in window], total, limit, offset)
