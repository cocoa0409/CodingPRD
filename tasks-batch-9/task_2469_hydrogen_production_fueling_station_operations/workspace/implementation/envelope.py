"""Response envelope construction (PRD 2.2 / 2.3)."""
import json
import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Response

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return iso_ms(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError("not JSON serializable: %r" % (obj,))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(db.now()),
    }


def respond(data, response_type="object", status=200, extra_meta=None):
    meta = _meta()
    if extra_meta:
        meta.update(extra_meta)
    payload = {"meta": meta, "response_type": response_type, "data": data}
    return Response(
        json.dumps(payload, default=_default),
        status=status,
        mimetype="application/json",
    )


def ok(data):
    return respond(data, "object", 200)


def created(data):
    return respond(data, "object", 201)


def listing(rows, limit, offset, total_count):
    return respond(
        rows,
        "array",
        200,
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        },
    )


def error_response(err):
    return respond(
        {"error_id": err.error_id, "message": err.message},
        "error",
        err.http_status,
    )
