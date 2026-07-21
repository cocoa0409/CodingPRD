"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""

import random
import string

from flask import jsonify

import store


def _request_id():
    body = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + body


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.iso(store.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(payload), status


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def paginate(items, args):
    total = len(items)
    limit = _int_arg(args.get("limit"), default=10)
    offset = _int_arg(args.get("offset"), default=0)
    if limit is None:
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset is None or offset < 0:
        offset = 0
    page = items[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def _int_arg(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
