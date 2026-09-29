"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def _clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _clean(data if data is not None else {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": _clean(list(rows))}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_params():
    """Validation priority 7: limit/offset range check -> ERR_INVALID_PAGINATION."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        limit = _int_arg(raw_limit)
        if limit is None or limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _int_arg(raw_offset)
        if offset is None or offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def _int_arg(raw):
    raw = raw.strip()
    if raw == "":
        return None
    try:
        if raw.startswith("+"):
            raw = raw[1:]
        neg = raw.startswith("-")
        digits = raw[1:] if neg else raw
        if not digits.isdigit():
            return None
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value


def paged(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)


def paged_with(rows, serializer, limit, offset):
    """Pagination when limit/offset were already validated earlier in the pipeline."""
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)
