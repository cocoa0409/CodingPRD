"""Response envelope — PRD §2.2 — and pagination — PRD §2.3."""
import json
import random
import string
from decimal import Decimal

from flask import Response, request

import store
from errors import bad_request

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(repr(value))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _send(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": store.public(data) if isinstance(data, dict) else (data or {}),
    }
    return _send(payload, status)


def created(data):
    return ok(data, 201)


def empty(status=200):
    return _send({"meta": _meta(), "response_type": "object", "data": {}}, status)


def page_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_v = LIMIT_DEFAULT
    else:
        try:
            limit_v = int(str(limit).strip())
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer.")
        if limit_v < LIMIT_MIN or limit_v > LIMIT_MAX:
            raise bad_request("limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_v = OFFSET_DEFAULT
    else:
        try:
            offset_v = int(str(offset).strip())
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer.")
        if offset_v < 0:
            raise bad_request("offset must be non-negative.")
    return limit_v, offset_v


def listing(rows):
    """Paginate an already-ordered list of rows and emit the array envelope."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [store.public(r) for r in window],
    }
    return _send(payload, 200)


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _send(payload, status)
