"""Response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def build_meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(db.clock),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    payload = {
        "meta": build_meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(payload), status


def error_response(error_id, message, status):
    payload = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
