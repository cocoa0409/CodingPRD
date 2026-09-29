"""Response envelope helpers.

Success envelope (PRD 2.2 / SCAFFOLD response_envelope.success):
    {"meta": {...}, "response_type": "object" | "array", "data": ...}
Error envelope:
    {"meta": {...}, "response_type": "error",
     "data": {"error_id": "...", "message": "..."}}

`meta` always carries api_request_id and api_request_timestamp.  List
responses additionally carry limit, offset, total_count and has_more; single
resource and error responses omit all four.
"""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request

import db
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_PARAM = "limit"
PAGINATION_OFFSET_PARAM = "offset"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso(db.now())}


def jsonable(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def serialize(rec):
    if rec is None:
        return None
    return jsonable(rec)


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": serialize(data) if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty_ok():
    return ok({}, 200)


def error_response(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


def read_pagination():
    """Parse and validate the pagination parameters."""
    raw_limit = request.args.get(PAGINATION_LIMIT_PARAM)
    raw_offset = request.args.get(PAGINATION_OFFSET_PARAM)
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def _as_int(raw):
    text = raw.strip()
    if text == "":
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    try:
        return int(text)
    except ValueError:
        return None


def page(rows):
    """Apply pagination to an already-ordered row list and emit the envelope."""
    limit, offset = read_pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta[PAGINATION_LIMIT_PARAM] = limit
    meta[PAGINATION_OFFSET_PARAM] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {"meta": meta, "response_type": "array",
            "data": [serialize(r) for r in window]}
    return jsonify(body), 200
