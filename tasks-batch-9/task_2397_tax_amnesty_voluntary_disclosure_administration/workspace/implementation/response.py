"""Response envelope helpers (PRD 2.2, 2.3)."""

import json
import random
import string
from decimal import Decimal

from flask import Response, request

import clock
from errors import err

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
        "api_request_timestamp": clock.wall_iso(),
    }


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def _emit(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    return _emit(
        {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}},
        status,
    )


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(api_error):
    return _emit(
        {
            "meta": _base_meta(),
            "response_type": "error",
            "data": {"error_id": api_error.error_id, "message": api_error.message},
        },
        api_error.http_status,
    )


def _int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise err("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise err("ERR_INVALID_PAGINATION")
    value = int(text)
    return value


def pagination():
    """Validate and return (limit, offset).  Raises ERR_INVALID_PAGINATION."""
    limit = _int_param(request.args.get("limit"))
    offset = _int_param(request.args.get("offset"))
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise err("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise err("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
