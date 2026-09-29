"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

import db
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.wall_now_iso(),
    }


def object_envelope(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def array_envelope(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_envelope(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def single(row, serializer, status=200):
    """Flush pending version bumps, then serialize one resource."""
    db.flush_dirty()
    return object_envelope(serializer(row), status)


def payload(data, status=200):
    db.flush_dirty()
    return object_envelope(data, status)


def _parse_page_param(raw, default, minimum, maximum=None):
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_PAGINATION")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_PAGINATION")
    return value


def pagination():
    limit = _parse_page_param(
        request.args.get("limit"), LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX
    )
    offset = _parse_page_param(
        request.args.get("offset"), OFFSET_DEFAULT, OFFSET_MIN, None
    )
    return limit, offset


def listing(rows, serializer, limit, offset):
    db.flush_dirty()
    total = len(rows)
    page = rows[offset: offset + limit]
    return array_envelope([serializer(r) for r in page], limit, offset, total)
