"""Response envelope helpers (PRD Section 2.2 and 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import db
from timeutil import fmt


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt(db.now()),
    }


def json_value(v):
    """Convert internal values to JSON-safe values."""
    if isinstance(v, datetime):
        return fmt(v)
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_value(x) for x in v]
    return v


def serialize(entity):
    """Public view of a stored entity: internal keys (``_``-prefixed) hidden."""
    return {k: json_value(v) for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200, pagination=None):
    body = {"meta": _meta(), "response_type": "object", "data": json_value(data)}
    if pagination is not None:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, pagination):
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serialize(i) for i in items],
    }
    body["meta"].update(pagination)
    return jsonify(body)


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def paginate(items, args):
    """Apply limit/offset query params (default 10, min 1, max 100; offset 0).

    Out-of-range values are clamped to the documented bounds.
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            from errors import err_invalid_request
            raise err_invalid_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            from errors import err_invalid_request
            raise err_invalid_request("offset must be an integer")
        offset = max(0, offset)

    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
