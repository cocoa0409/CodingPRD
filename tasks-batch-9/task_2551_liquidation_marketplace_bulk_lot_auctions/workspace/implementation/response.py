"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

from errors import ApiError
from util import iso, now_wall, request_id

LIMIT_PARAM = "limit"
OFFSET_PARAM = "offset"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(now_wall()),
    }


def success(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return success(data, 201)


def collection(rows, limit, offset, total_count):
    meta = _base_meta()
    meta[LIMIT_PARAM] = limit
    meta[OFFSET_PARAM] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def bare_array(rows):
    """Sweep endpoints: an array payload without pagination metadata."""
    body = {
        "meta": _base_meta(),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def _positive_int(raw):
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    if not text or not text.lstrip("-").isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    return int(text)


def pagination_params():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get(LIMIT_PARAM)
    raw_offset = request.args.get(OFFSET_PARAM)
    if raw_limit is not None:
        limit = _positive_int(raw_limit)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "%s must be between %d and %d." % (LIMIT_PARAM, LIMIT_MIN, LIMIT_MAX),
            )
    if raw_offset is not None:
        offset = _positive_int(raw_offset)
        if offset < OFFSET_MIN:
            raise ApiError(
                "ERR_INVALID_REQUEST", "%s must not be negative." % OFFSET_PARAM
            )
    return limit, offset


def window(rows, limit, offset):
    return rows[offset:offset + limit]
