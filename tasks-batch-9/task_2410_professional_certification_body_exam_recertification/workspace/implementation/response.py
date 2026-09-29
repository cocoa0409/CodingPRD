"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime

from flask import jsonify, request

from errors import ApiError
from util import UTC, fmt_ts

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(UTC)),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def array_response(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _strict_int(text):
    if text is None:
        return None
    raw = text.strip()
    if not raw:
        return None
    negative = raw.startswith("-")
    digits = raw[1:] if negative or raw.startswith("+") else raw
    if not digits.isdigit():
        return None
    return -int(digits) if negative else int(digits)


def read_pagination():
    """PRD 2.3: limit defaults to 10, minimum 1, maximum 100; offset defaults 0.

    A limit outside the accepted range, or a non-integer value for either
    parameter, is a malformed request.
    """
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in request.args:
        limit = _strict_int(request.args.get("limit"))
        if limit is None or limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST")
    if "offset" in request.args:
        offset = _strict_int(request.args.get("offset"))
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    return limit, offset


def bool_filter(name):
    """Read an exact-match boolean query filter, or None when absent."""
    if name not in request.args:
        return None
    raw = (request.args.get(name) or "").strip().lower()
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST")


def apply_filters(rows, spec):
    """Exact-match filters. `spec` maps query parameter name -> record field."""
    for param, field in spec.items():
        if param not in request.args:
            continue
        wanted = request.args.get(param)
        rows = [r for r in rows if _as_text(r.get(field)) == wanted]
    return rows


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return value


def paginate(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)
