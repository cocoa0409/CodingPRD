"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import fail
from store import db, fmt_ts

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(raw, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    text = str(raw).strip()
    if not (text.lstrip("+-").isdigit()) or text.lstrip("+-") == "":
        fail("ERR_INVALID_REQUEST")
    value = int(text)
    if value < minimum:
        fail("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST")
    return value


def pagination():
    limit = _int_param(request.args.get("limit"), PAGE_LIMIT_DEFAULT,
                       PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param(request.args.get("offset"), PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paged(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
