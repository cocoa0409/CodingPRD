"""Response envelope helpers (PRD 2.2)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


def _emit(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)
