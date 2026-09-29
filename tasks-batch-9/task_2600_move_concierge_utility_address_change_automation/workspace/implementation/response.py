"""Response envelope helpers: meta / response_type / data, plus pagination."""

import json
import random
import string
from decimal import Decimal

from flask import Response, request

import db
from errors import ApiError, ERROR_HTTP

ALNUM = string.ascii_lowercase + string.digits

LIMIT_FIELD = "limit"
OFFSET_FIELD = "offset"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def api_request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _encode(payload):
    return json.dumps(payload, default=_default)


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


def ok(data, status=200, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return Response(_encode(body), status=status, mimetype="application/json")


def created(data):
    return ok(data, status=201)


def error_response(error_id, message, http_status=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    status = http_status or ERROR_HTTP.get(error_id, 400)
    return Response(_encode(body), status=status, mimetype="application/json")


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is above its maximum." % name)
    return value


def pagination():
    limit = _int_param(LIMIT_FIELD, LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param(OFFSET_FIELD, OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginated(rows):
    """Apply created_at-ascending ordering plus offset pagination to rows."""
    limit, offset = pagination()
    ordered = sorted(rows, key=db.order_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta_extra = {
        LIMIT_FIELD: limit,
        OFFSET_FIELD: offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return ok([db.public(r) for r in window], meta_extra=meta_extra)


def match_filters(rows, spec):
    """Conjunctive equality filtering driven by query parameters.

    spec maps query parameter name -> record field name.
    """
    out = list(rows)
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if raw in ("true", "false"):
            wanted = (raw == "true")
            out = [r for r in out if r.get(field) is wanted or r.get(field) == wanted]
        else:
            out = [r for r in out if str(r.get(field)) == raw]
    return out
