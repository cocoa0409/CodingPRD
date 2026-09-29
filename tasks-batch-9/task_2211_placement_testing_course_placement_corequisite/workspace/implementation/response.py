"""Response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def iso(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


# PRD 2.4 pins exactly two row properties to three fractional digits.  Every
# other datetime is simply "ISO 8601 UTC" (PRD 2.6), rendered at the precision
# the instant actually carries.
MILLIS_FIELDS = ("created_at", "updated_at")


def iso_seconds(value):
    if value is None:
        return None
    if value.microsecond:
        return iso(value)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def jsonable(value, key=None):
    if isinstance(value, datetime):
        return iso(value) if key in MILLIS_FIELDS else iso_seconds(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict(
            (k, jsonable(v, k)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(v, key) for v in value]
    return value


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


def ok_list(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(i) for i in items],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
