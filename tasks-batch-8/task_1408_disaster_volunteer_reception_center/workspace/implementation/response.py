"""Standard response envelope helpers (PRD section 2.2)."""

import secrets
import string

from flask import jsonify

import db


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.fmt_ts(db.now()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0.

    Out-of-range or malformed values are clamped to the documented bounds.
    """
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return {"limit": limit, "offset": offset}


def paginate(records, args):
    """Sort by created_at ascending and apply limit/offset windowing."""
    params = parse_pagination(args)
    ordered = sorted(records, key=lambda r: (r["created_at_dt"], r["_seq"]))
    total = len(ordered)
    start = params["offset"]
    end = start + params["limit"]
    window = ordered[start:end]
    pagination = {
        "limit": params["limit"],
        "offset": params["offset"],
        "total_count": total,
        "has_more": end < total,
    }
    return window, pagination
