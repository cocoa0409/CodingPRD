"""Response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string

from flask import jsonify, request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from db import db
from errors import fail
from timeutil import now_real_iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_real_iso()}


def success(data, status=200):
    db.finalize()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return success(data, 201)


def collection(rows, serializer, sort_key=None, reverse=False):
    """Paginate + serialize a list result."""
    limit, offset = read_pagination()
    if sort_key is not None:
        rows = sorted(rows, key=sort_key, reverse=reverse)
    total = len(rows)
    window = rows[offset : offset + limit]
    db.finalize()
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    db.finalize()
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        fail("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    value = int(text)
    return value


def read_pagination():
    limit = _int_param(request.args.get("limit"))
    offset = _int_param(request.args.get("offset"))
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        fail(
            "ERR_INVALID_REQUEST",
            "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
        )
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def enum_filter(name, allowed):
    """Read an optional query filter, refusing unrecognised enum members."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Unrecognised %s filter value." % name)
    return raw


def str_filter(name):
    return request.args.get(name)


def by_created_asc(rec):
    return rec["_seq"]


def by_created_desc(rec):
    return rec["_seq"]
