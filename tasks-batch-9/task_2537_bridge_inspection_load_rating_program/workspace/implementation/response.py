"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""

import json
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import Response

import db

_ALNUM = string.ascii_uppercase + string.digits

# Pagination contract (PRD 2.3).
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": db.fmt_dt(db.now()),
    }


def _default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return db.fmt_dt(value)
    if isinstance(value, date):
        return db.fmt_date(value)
    raise TypeError("not serializable: %r" % (value,))


def _json_response(body, status):
    text = json.dumps(body, default=_default)
    return Response(text, status=status, mimetype="application/json")


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return _json_response(body, status)


def empty_response(status=204):
    return Response("", status=status, mimetype="application/json")


def list_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return _json_response(body, 200)


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json_response(body, status)


def paginate(records, limit, offset):
    total = len(records)
    return records[offset : offset + limit], total
