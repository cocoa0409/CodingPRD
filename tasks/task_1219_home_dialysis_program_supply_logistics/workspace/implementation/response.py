"""Response envelope helpers per PRD §2.2 / §2.3."""
import random
import string

from flask import jsonify

import db


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }
    if pagination:
        m.update(pagination)
    return m


def _strip_private(v):
    if isinstance(v, dict):
        return {k: _strip_private(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [_strip_private(x) for x in v]
    return v


def success_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": _strip_private(data)}
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array",
            "data": _strip_private(items)}
    return jsonify(body), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit default 10, min 1, max 100; offset default 0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, args):
    limit, offset = parse_pagination(args)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
