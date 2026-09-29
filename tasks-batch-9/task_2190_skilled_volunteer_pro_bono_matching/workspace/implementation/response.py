"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response, request

from errors import ApiError
from store import fmt_iso, now

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": fmt_iso(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(payload, status):
    body = json.dumps(jsonable(payload))
    return Response(body, status=status, mimetype="application/json")


def ok(data=None, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _emit(payload, status)


def created(data=None):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    payload = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(rows)) < total_count,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return _emit(payload, 200)


def error_response(err):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _emit(payload, err.http_status)


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
    """Validated (limit, offset) -- priority 18 of the rejection ladder."""
    limit = _int_param(
        "limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX
    )
    offset = _int_param(
        "offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN, None
    )
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)
