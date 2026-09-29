"""Response envelope helpers (PRD 2.2 / 2.3)."""
import json
import uuid
from decimal import Decimal

from flask import Response

import clock

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + uuid.uuid4().hex


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("not serialisable: %r" % (obj,))


def _dump(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _dump({"meta": _meta(), "response_type": "object", "data": data}, status)


def array_response(items, limit, offset, total_count, status=200):
    has_more = offset + len(items) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return _dump({"meta": meta, "response_type": "array", "data": items}, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _dump(payload, status)
