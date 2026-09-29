"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify, request

from db import now_str
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_str()}
    if extra:
        m.update(extra)
    return m


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": jsonable(data) if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(rows) < total,
    }
    body = {"meta": meta(page_meta), "response_type": "array", "data": jsonable(rows)}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _parse_page_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(text)
    return value


def pagination():
    limit = _parse_page_int(request.args.get("limit"))
    offset = _parse_page_int(request.args.get("offset"))
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


def listing(rows):
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if str(r.get(field)) == value]


def apply_filters(rows, fields):
    for field in fields:
        rows = filter_eq(rows, field, request.args.get(field))
    return rows
