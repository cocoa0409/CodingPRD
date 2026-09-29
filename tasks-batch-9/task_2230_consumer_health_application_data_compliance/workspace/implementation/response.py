"""Response envelope construction (PRD 2.2, 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

import clock
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        # request metadata rather than a domain instant: real UTC wall clock
        "api_request_timestamp": clock.fmt(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not text:
        return default
    try:
        value = int(text, 10)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        fail("ERR_INVALID_REQUEST", "%s is outside its accepted range." % name)
    return value


def pagination():
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)
