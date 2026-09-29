"""Response envelope helpers.

PRD section 2.2 pins the envelope exactly:

    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "...",
                "limit": .., "offset": .., "total_count": .., "has_more": .. },
      "response_type": "object" | "array" | "error",
      "data": {} }
"""

import json
import random
import string
from decimal import Decimal

from flask import Response

import store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("Object of type %s is not JSON serializable" % type(value).__name__)


def _json(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return _json(payload, status)


def created(data):
    return ok(data, 201)


def collection(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return _json(payload, 200)


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json(payload, status)
