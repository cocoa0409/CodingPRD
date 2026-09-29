"""Standard response envelope (PRD section 2.2 / SCAFFOLD response_envelope)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

from store import wall_now_iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)


def _json_response(body, status):
    return Response(
        json.dumps(body, default=_default),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return _json_response(body, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return _json_response(body, 200)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json_response(body, status)
