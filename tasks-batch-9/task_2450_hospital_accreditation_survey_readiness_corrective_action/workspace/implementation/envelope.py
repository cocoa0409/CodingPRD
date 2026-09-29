"""Response envelope helpers (PRD 2.2)."""

import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return iso(obj)
    raise TypeError("not serializable: %r" % (obj,))


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.clock),
    }


def _respond(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return _respond(payload, status)


def array_response(data, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": data}
    return _respond(payload, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)
