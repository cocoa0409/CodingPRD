"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ERR_INVALID_REQUEST, ApiError
from timeutil import wall_now_iso

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": wall_now_iso()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
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


def _int_param(raw, name):
    if isinstance(raw, bool) or raw is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer." % name)
    text = str(raw).strip()
    if not text:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer." % name)
    value = int(text)
    return value


def pagination():
    """Read `limit`/`offset` from the query string, enforcing PRD 2.3 bounds."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _int_param(raw_limit, "limit")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _int_param(raw_offset, "offset")
        if offset < PAGE_OFFSET_MIN:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be zero or greater.")
    return limit, offset


def paginate(rows):
    """Apply the request's page window and emit the list envelope."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response(window, limit, offset, total)
