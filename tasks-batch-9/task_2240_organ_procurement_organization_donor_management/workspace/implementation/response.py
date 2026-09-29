"""Response envelope helpers (PRD 2.2, 2.3, 2.4)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, Z-suffixed."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


def convert(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: convert(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [convert(v) for v in value]
    return value


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, (list, tuple)) else "object",
        "data": convert(data),
    }
    return jsonify(body), status


def paginated(rows, limit, offset, total_count):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(rows)) < total_count,
            }
        ),
        "response_type": "array",
        "data": convert(list(rows)),
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
