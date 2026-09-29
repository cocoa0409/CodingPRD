"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime
from decimal import Decimal

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def jsonable(value):
    """Convert internal representations (datetime / Decimal) into JSON values."""
    if isinstance(value, datetime):
        return clock.iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def meta(extra=None):
    body = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    if extra:
        body.update(extra)
    return body


def success(data, status=200):
    return (
        {
            "meta": meta(),
            "response_type": "object",
            "data": jsonable(data),
        },
        status,
    )


def collection(items, limit, offset, total_count):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return (
        {
            "meta": meta(page),
            "response_type": "array",
            "data": jsonable(items),
        },
        200,
    )


def error(error_id, message, status):
    return (
        {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
