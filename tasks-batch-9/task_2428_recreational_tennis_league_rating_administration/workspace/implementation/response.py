"""Response envelope helpers (PRD 2.2 / 2.3)."""

from flask import jsonify, request

from errors import ApiError
from store import new_request_id, wall_now_iso

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def no_content_response():
    return "", 204


def array_response(rows, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(raw):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    neg = text.startswith("-")
    digits = text[1:] if neg else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(digits)
    return -value if neg else value


def pagination():
    """Read limit/offset from the query string, enforcing PRD 2.3 bounds."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        limit = _int_param(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        offset = _int_param(raw_offset)
        if offset < PAGE_OFFSET_MIN:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, serializer=None):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    if serializer is not None:
        page = [serializer(r) for r in page]
    return array_response(page, total, limit, offset)
