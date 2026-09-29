"""Response envelope helpers (PRD 2.2 / scaffold section 1.0)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def _now_stamp():
    now = datetime.now(timezone.utc)
    return fmt_dt(now.replace(tzinfo=None))


def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def serialize(rec):
    """Public projection of a stored row: internal keys are prefixed with '_'."""
    return dict(
        (k, jsonable(v)) for k, v in rec.items() if not k.startswith("_")
    )


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": _now_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(rows) < total_count,
            }
        ),
        "response_type": "array",
        "data": [jsonable(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
