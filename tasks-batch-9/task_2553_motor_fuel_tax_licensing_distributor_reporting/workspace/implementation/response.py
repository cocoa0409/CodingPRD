"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALPHABET = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }


def object_response(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_PAGINATION")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_PAGINATION")
    return value


def pagination():
    """limit / offset with the defaults, minimum and maximum of PRD 2.3."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(rows, serializer, status=200):
    """A paginated list.  total_count is the pre-pagination match count."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), status
