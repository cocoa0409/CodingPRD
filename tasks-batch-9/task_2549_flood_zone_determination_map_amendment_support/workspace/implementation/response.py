"""Response envelope helpers (PRD section 2.2 / scaffold response_envelope)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from db import db

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def fmt_ts(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def clean(value):
    if isinstance(value, dict):
        return dict(
            (k, clean(v)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": clean(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": clean(list(rows))}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total
