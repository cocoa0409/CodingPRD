"""Standard response envelope per SCAFFOLD.yaml §1.0 / PRD §2.2."""
import secrets
import string

from flask import jsonify

import db
from util import iso


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def success(data, status=200, pagination=None):
    """data must already be JSON-able. pagination = dict(limit, offset, total_count, has_more)."""
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def paginate(items):
    """Apply limit/offset from the query string; returns (page, pagination-meta)."""
    from flask import request

    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _parse("limit", 10)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    offset = _parse("offset", 0)
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
