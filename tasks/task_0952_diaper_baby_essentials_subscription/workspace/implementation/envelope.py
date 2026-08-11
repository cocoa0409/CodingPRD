"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, date
from decimal import Decimal

from flask import jsonify, request

import constants as C
import store
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.real_now_iso(),
    }


def jsonable(value):
    """Recursively coerce datetimes/dates/Decimals so that NO field can ever
    render as an HTTP-date or as a float artefact."""
    if isinstance(value, datetime):
        return store.fmt_instant(value)
    if isinstance(value, date):
        return store.fmt_date(value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(rows)}
    return jsonify(body), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def _parse_pagination_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    limit = _parse_pagination_int(request.args.get("limit"))
    offset = _parse_pagination_int(request.args.get("offset"))
    if limit is None:
        limit = C.PAGINATION_DEFAULT_LIMIT
    if offset is None:
        offset = C.PAGINATION_DEFAULT_OFFSET
    if limit < C.PAGINATION_MIN_LIMIT or limit > C.PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, serializer):
    """Order by created_at ascending (PRD 2.3), then page, then serialize."""
    limit, offset = pagination()
    ordered = store.by_created(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
