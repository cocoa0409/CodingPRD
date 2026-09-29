"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify, request

from db import fmt_ts, ordered, real_now
from errors import fail

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(real_now()),
    }


def to_json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json_value(v) for k, v in value.items()}
    return value


def serialize(row):
    """Public projection of a stored row: every non-underscore key."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = to_json_value(value)
    return out


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def object_response(row, status=200):
    return ok(serialize(row), status)


def created_response(row):
    return ok(serialize(row), 201)


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = str(raw).strip()
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(rows, sort=True):
    limit, offset = pagination()
    items = ordered(rows) if sort else list(rows)
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
