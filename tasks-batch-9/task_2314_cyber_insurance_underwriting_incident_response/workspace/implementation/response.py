"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response, request

from db import public
from errors import bad_request

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_clock_iso():
    moment = datetime.now(timezone.utc)
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def _json_default(value):
    if isinstance(value, Decimal):
        as_int = int(value)
        if value == as_int:
            return float(as_int)
        return float(value)
    raise TypeError(repr(value) + " is not JSON serializable")


def _emit(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_clock_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": public(data) if isinstance(data, dict) else data}, status)


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)


def _page_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise bad_request("%s must be an integer" % name)
    if str(raw).strip() != str(value):
        # tolerate leading '+' style inputs only when they round-trip
        if str(raw).strip().lstrip("+") != str(value):
            raise bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %d" % (name, maximum))
    return value


def listing(rows):
    """Paginate an already-ordered list of rows and emit the array envelope."""
    limit = _page_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _page_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    payload = {
        "meta": _meta(meta),
        "response_type": "array",
        "data": [public(row) for row in page],
    }
    return _emit(payload, 200)
